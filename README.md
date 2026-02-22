# flask-service

A lightweight Flask microservice designed for containerized deployment on OpenShift/Kubernetes.

## Project Structure

```
flask_service/
├── app/
│   ├── __init__.py          # Application factory
│   ├── config.py            # Configuration via environment variables
│   └── routes/
│       ├── api.py           # API endpoints (/api/v1/...)
│       └── health.py        # Health check endpoints (/healthz, /readyz)
├── openshift/
│   └── deployment.yaml      # Deployment, Service, and Route manifests
├── Dockerfile               # Container image (UBI 9 + Python 3.11)
├── gunicorn.conf.py         # Gunicorn server configuration
├── requirements.txt         # Python dependencies
└── wsgi.py                  # WSGI entry point
```

## Getting Started

### Local Development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python wsgi.py
```

The service will be available at `http://localhost:8080`.

### Running with Gunicorn

```bash
gunicorn --config gunicorn.conf.py wsgi:application
```

### Docker

```bash
docker build -t flask-service .
docker run -p 8080:8080 flask-service
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/healthz` | Liveness probe |
| GET | `/readyz` | Readiness probe |
| GET | `/api/v1/example` | Example endpoint |

## Configuration

Environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `LOG_LEVEL` | `info` | Logging level |
| `GUNICORN_WORKERS` | `4` | Number of Gunicorn worker processes |
| `GUNICORN_THREADS` | `2` | Threads per worker |
| `GUNICORN_TIMEOUT` | `120` | Worker timeout in seconds |
| `FLASK_DEBUG` | `false` | Enable Flask debug mode |

## OpenShift Deployment

```bash
oc apply -f openshift/deployment.yaml
```

This creates a Deployment, Service, and Route with TLS edge termination.
