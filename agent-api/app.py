import os
import re
import time
from flask import Flask, request, jsonify
from prometheus_client import Counter, Gauge, Histogram, generate_latest, CONTENT_TYPE_LATEST
from werkzeug.exceptions import BadRequest, UnsupportedMediaType

app = Flask(__name__)

PROMPT_VERSION = os.environ.get('PROMPT_VERSION', 'v1.0.0')

PAYLOAD_SIZE_BUCKETS = [0, 64, 128, 256, 512, 1024, 2048, 4096, 8192, 16384, 32768]
MESSAGE_LENGTH_BUCKETS = [0, 25, 50, 100, 200, 500, 1000, 2000, 4000, 8000]
PHASE_LATENCY_BUCKETS = [0.0001, 0.0005, 0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0]

# Prometheus metrics

# Request throughput by route helps detect traffic drops and separate user traffic from health checks.
REQUEST_COUNT = Counter(
    'agent_requests_total',
    'Total number of requests to the agent API',
    ['prompt_version', 'route']
)

# Safety rejections by reason help on-call engineers distinguish attacks from policy or prompt-version drift.
REJECTION_COUNT = Counter(
    'agent_rejections_total',
    'Total number of safety rejections by reason',
    ['prompt_version', 'reason']
)

# Request outcomes connect HTTP status codes with product semantics such as accepted, rejected, or invalid.
REQUEST_OUTCOMES = Counter(
    'agent_request_outcomes_total',
    'Total number of request outcomes for the agent API',
    ['prompt_version', 'route', 'status_code', 'outcome']
)

# Invalid request reasons expose client/schema regressions separately from agent safety behavior.
INVALID_REQUEST_COUNT = Counter(
    'agent_invalid_requests_total',
    'Total number of invalid requests to the agent API',
    ['prompt_version', 'route', 'reason']
)

# Payload size catches oversized or malformed traffic before JSON parsing succeeds.
REQUEST_PAYLOAD_SIZE = Histogram(
    'agent_request_payload_bytes',
    'Raw request payload size in bytes',
    ['route', 'outcome'],
    buckets=PAYLOAD_SIZE_BUCKETS
)

# Message length shows prompt-size trends that can explain latency or abuse spikes.
MESSAGE_LENGTH = Histogram(
    'agent_message_length_chars',
    'Message length in characters for valid agent requests',
    ['prompt_version', 'outcome'],
    buckets=MESSAGE_LENGTH_BUCKETS
)

# End-to-end latency remains the primary user-visible performance signal by route.
REQUEST_LATENCY = Histogram(
    'agent_request_latency_seconds',
    'Request latency in seconds',
    ['prompt_version', 'route'],
    buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0]
)

# Classification latency isolates slowdowns in the safety decision path.
CLASSIFICATION_LATENCY = Histogram(
    'agent_classification_latency_seconds',
    'Time spent classifying whether a message should be rejected',
    ['prompt_version', 'outcome'],
    buckets=PHASE_LATENCY_BUCKETS
)

# Generation latency isolates slowdowns after a request has passed safety checks.
GENERATION_LATENCY = Histogram(
    'agent_generation_latency_seconds',
    'Time spent generating a response for accepted messages',
    ['prompt_version'],
    buckets=PHASE_LATENCY_BUCKETS
)

# Prompt version info lets dashboards correlate behavior changes with the active prompt rollout.
PROMPT_VERSION_INFO = Gauge(
    'agent_prompt_version_info',
    'Active prompt version for this agent API instance',
    ['prompt_version']
)
PROMPT_VERSION_INFO.labels(prompt_version=PROMPT_VERSION).set(1)

# Rejection patterns - deterministic classification based on message content
REJECTION_PATTERNS = {
    'prompt_injection': [
        r'ignore\s+(all\s+)?(previous\s+)?instructions',
        r'system\s+prompt',
        r'disregard\s+(all\s+)?(previous\s+)?',
        r'forget\s+(all\s+)?(previous\s+)?instructions',
        r'new\s+instructions',
        r'override\s+(all\s+)?rules',
        r'jailbreak',
        r'bypass\s+(safety|filter|restriction)',
    ],
    'secrets_request': [
        r'password',
        r'api[\s_-]?key',
        r'secret[\s_-]?key',
        r'access[\s_-]?token',
        r'private[\s_-]?key',
        r'credentials',
        r'auth[\s_-]?token',
        r'bearer[\s_-]?token',
    ],
    'dangerous_action': [
        r'restart\s+prod',
        r'delete\s+(the\s+)?database',
        r'drop\s+table',
        r'rm\s+-rf',
        r'shutdown\s+server',
        r'execute\s+command',
        r'run\s+as\s+root',
        r'sudo\s+',
        r'format\s+(hard\s+)?drive',
        r'wipe\s+(all\s+)?data',
    ],
}


def classify_rejection(message: str) -> tuple[bool, str | None]:
    """
    Classify whether a message should be rejected and return the reason.
    Returns (rejected, reason) tuple.
    """
    message_lower = message.lower()
    
    for reason, patterns in REJECTION_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, message_lower):
                return True, reason
    
    return False, None


def generate_response(message: str) -> str:
    """Generate a simple response for accepted messages."""
    responses = [
        f"I understand you're asking about: {message[:50]}...",
        "That's an interesting question. Let me help you with that.",
        "I'd be happy to assist with your request.",
        "Thank you for your question. Here's what I can tell you.",
    ]
    return responses[hash(message) % len(responses)]


def get_request_payload_size() -> int:
    """Return the raw request payload size without depending on successful JSON parsing."""
    if request.content_length is not None:
        return request.content_length
    return len(request.get_data(cache=True) or b'')


def record_request_outcome(route: str, status_code: int, outcome: str) -> None:
    """Record one bounded request outcome with the actual returned HTTP status code."""
    REQUEST_OUTCOMES.labels(
        prompt_version=PROMPT_VERSION,
        route=route,
        status_code=str(status_code),
        outcome=outcome
    ).inc()


@app.route('/ask', methods=['POST'])
def ask():
    """
    Main endpoint for asking the agent.
    Accepts JSON with 'message' field.
    Returns rejection status, reason, prompt version, and answer.
    """
    start_time = time.time()
    payload_size = 0
    outcome_recorded = False
    payload_observed = False
    
    REQUEST_COUNT.labels(prompt_version=PROMPT_VERSION, route='/ask').inc()
    
    try:
        payload_size = get_request_payload_size()

        def observe_payload_size(outcome: str) -> None:
            nonlocal payload_observed
            REQUEST_PAYLOAD_SIZE.labels(route='/ask', outcome=outcome).observe(payload_size)
            payload_observed = True

        def build_response(response_body: dict, status_code: int, outcome: str):
            nonlocal outcome_recorded
            response = jsonify(response_body)
            observe_payload_size(outcome)
            record_request_outcome('/ask', status_code, outcome)
            outcome_recorded = True
            return response, status_code

        def build_invalid_response(invalid_reason: str, error: str):
            INVALID_REQUEST_COUNT.labels(
                prompt_version=PROMPT_VERSION,
                route='/ask',
                reason=invalid_reason
            ).inc()
            return build_response({
                'error': error,
                'rejected': True,
                'reason': 'invalid_request',
                'prompt_version': PROMPT_VERSION,
                'answer': None
            }, 400, 'invalid_request')

        try:
            data = request.get_json()
        except (BadRequest, UnsupportedMediaType):
            return build_invalid_response('malformed_json', 'Invalid JSON payload')

        if not isinstance(data, dict) or 'message' not in data:
            return build_invalid_response('missing_message', 'Missing required field: message')

        message = data['message']
        if not isinstance(message, str):
            return build_invalid_response('invalid_message_type', 'Field message must be a string')

        if not message.strip():
            return build_invalid_response('empty_message', 'Field message must not be empty')

        classification_start = time.perf_counter()
        rejected, reason = classify_rejection(message)
        classification_latency = time.perf_counter() - classification_start
        outcome = 'rejected' if rejected else 'accepted'
        CLASSIFICATION_LATENCY.labels(
            prompt_version=PROMPT_VERSION,
            outcome=outcome
        ).observe(classification_latency)
        MESSAGE_LENGTH.labels(
            prompt_version=PROMPT_VERSION,
            outcome=outcome
        ).observe(len(message))

        if rejected:
            REJECTION_COUNT.labels(
                prompt_version=PROMPT_VERSION,
                reason=reason
            ).inc()
            response = {
                'rejected': True,
                'reason': reason,
                'prompt_version': PROMPT_VERSION,
                'answer': f"I cannot process this request due to: {reason}"
            }
            return build_response(response, 200, outcome)

        generation_start = time.perf_counter()
        answer = generate_response(message)
        generation_latency = time.perf_counter() - generation_start
        GENERATION_LATENCY.labels(prompt_version=PROMPT_VERSION).observe(generation_latency)

        response = {
            'rejected': False,
            'reason': None,
            'prompt_version': PROMPT_VERSION,
            'answer': answer
        }
        return build_response(response, 200, outcome)
    except Exception:
        if not payload_observed:
            REQUEST_PAYLOAD_SIZE.labels(route='/ask', outcome='unexpected_error').observe(payload_size)
        if not outcome_recorded:
            record_request_outcome('/ask', 500, 'unexpected_error')
        raise
    finally:
        latency = time.time() - start_time
        REQUEST_LATENCY.labels(prompt_version=PROMPT_VERSION, route='/ask').observe(latency)


@app.route('/healthz', methods=['GET'])
def healthz():
    """Health check endpoint."""
    REQUEST_COUNT.labels(prompt_version=PROMPT_VERSION, route='/healthz').inc()
    response = jsonify({
        'status': 'healthy',
        'prompt_version': PROMPT_VERSION
    })
    record_request_outcome('/healthz', 200, 'health_check')
    return response, 200


@app.route('/metrics', methods=['GET'])
def metrics():
    """Prometheus metrics endpoint."""
    return generate_latest(), 200, {'Content-Type': CONTENT_TYPE_LATEST}


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=False)
