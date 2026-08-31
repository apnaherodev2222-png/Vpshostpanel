"""
core/docker_manager.py
Thin wrapper around the docker SDK for building/running/stopping
per-bot containers. Falls back gracefully if the Docker daemon
isn't reachable (caller should catch DockerUnavailable).
"""

import os
import config

try:
    import docker
    from docker.errors import DockerException
except ImportError:  # docker package not installed
    docker = None
    DockerException = Exception


class DockerUnavailable(Exception):
    pass


def _client():
    if docker is None:
        raise DockerUnavailable("docker SDK not installed")
    try:
        return docker.from_env()
    except DockerException as e:
        raise DockerUnavailable(str(e))


DOCKERFILE_PYTHON = """FROM {base_image}
WORKDIR /app
COPY . /app
RUN if [ -f requirements.txt ]; then pip install --no-cache-dir -r requirements.txt; fi
CMD ["python", "{entrypoint}"]
"""

DOCKERFILE_NODE = """FROM {base_image}
WORKDIR /app
COPY . /app
RUN if [ -f package.json ]; then npm install --omit=dev; fi
CMD ["node", "{entrypoint}"]
"""


def write_dockerfile(project_path: str, runtime: str, entrypoint: str):
    if runtime == "python":
        content = DOCKERFILE_PYTHON.format(base_image=config.DOCKER_IMAGE_PYTHON, entrypoint=entrypoint)
    elif runtime == "node":
        content = DOCKERFILE_NODE.format(base_image=config.DOCKER_IMAGE_NODE, entrypoint=entrypoint)
    else:
        raise ValueError(f"Unsupported runtime: {runtime}")

    dockerfile_path = os.path.join(project_path, "Dockerfile")
    with open(dockerfile_path, "w") as f:
        f.write(content)
    return dockerfile_path


def build_image(project_path: str, image_tag: str):
    client = _client()
    image, logs = client.images.build(path=project_path, tag=image_tag, rm=True, forcerm=True)
    return image, [l.get("stream", "") for l in logs if "stream" in l]


def run_container(image_tag: str, container_name: str, env_vars: dict | None = None):
    client = _client()
    # Remove any stale container with the same name first
    try:
        old = client.containers.get(container_name)
        old.remove(force=True)
    except Exception:
        pass

    container = client.containers.run(
        image_tag,
        name=container_name,
        detach=True,
        environment=env_vars or {},
        mem_limit=config.CONTAINER_MEMORY_LIMIT,
        nano_cpus=int(config.CONTAINER_CPU_LIMIT * 1_000_000_000),
        restart_policy={"Name": "no"},
    )
    return container.id


def stop_container(container_id: str):
    client = _client()
    try:
        c = client.containers.get(container_id)
        c.stop(timeout=10)
    except Exception:
        pass


def remove_container(container_id: str):
    client = _client()
    try:
        c = client.containers.get(container_id)
        c.remove(force=True)
    except Exception:
        pass


def restart_container(container_id: str):
    client = _client()
    c = client.containers.get(container_id)
    c.restart(timeout=10)


def get_logs(container_id: str, tail: int = 100) -> str:
    client = _client()
    c = client.containers.get(container_id)
    return c.logs(tail=tail).decode(errors="replace")


def get_stats(container_id: str) -> dict:
    client = _client()
    c = client.containers.get(container_id)
    c.reload()
    stats = c.stats(stream=False)

    cpu_delta = stats["cpu_stats"]["cpu_usage"]["total_usage"] - stats["precpu_stats"]["cpu_usage"]["total_usage"]
    system_delta = stats["cpu_stats"].get("system_cpu_usage", 0) - stats["precpu_stats"].get("system_cpu_usage", 0)
    cpu_percent = 0.0
    if system_delta > 0 and cpu_delta > 0:
        online_cpus = stats["cpu_stats"].get("online_cpus", 1)
        cpu_percent = (cpu_delta / system_delta) * online_cpus * 100.0

    mem_usage = stats["memory_stats"].get("usage", 0)
    mem_limit = stats["memory_stats"].get("limit", 1)

    return {
        "status": c.status,
        "cpu_percent": round(cpu_percent, 2),
        "mem_usage_mb": round(mem_usage / 1024 / 1024, 1),
        "mem_limit_mb": round(mem_limit / 1024 / 1024, 1),
    }


def is_docker_available() -> bool:
    try:
        _client().ping()
        return True
    except Exception:
        return False
