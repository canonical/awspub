import tomllib

LOCK = 'poetry.lock'


def _get_requirements() -> list[str]:
    c = _read_config()

    deps = set()

    for dep in c["package"]:
        deps.add(dep['name'])

    return list(deps)


def _read_config() -> dict:
    with open(LOCK, 'rb') as f:
        config = tomllib.load(f)
    return config
