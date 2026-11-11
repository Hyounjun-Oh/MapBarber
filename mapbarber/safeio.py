"""Writing files so that a failure half-way never leaves a damaged file behind."""
import os
from contextlib import contextmanager


def partial(path):
    """Name of the temporary file a write to `path` goes through; it keeps the extension."""
    folder, name = os.path.split(path)
    stem, ext = os.path.splitext(name)
    return os.path.join(folder, f".{stem}.part{ext}")


@contextmanager
def replacing(*paths):
    """Yield one temporary path per target; they replace the targets only if the block finishes without error."""
    temporary = [partial(path) for path in paths]
    try:
        yield temporary if len(temporary) > 1 else temporary[0]
        for source, target in zip(temporary, paths):
            os.replace(source, target)
    finally:
        for leftover in temporary:
            if os.path.exists(leftover):
                os.remove(leftover)
