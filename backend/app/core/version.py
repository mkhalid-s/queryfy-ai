# ============================================
# QueryfyAI - Centralized Version Management
# ============================================
# Single source of truth for application version.
# Update this file when releasing new versions.
#
# Versioning follows Semantic Versioning (SemVer):
#   MAJOR.MINOR.PATCH
#   - MAJOR: Breaking changes
#   - MINOR: New features (backward compatible)
#   - PATCH: Bug fixes (backward compatible)
# ============================================

__version__ = "1.2.0"

# Version components for programmatic access
VERSION_MAJOR = 1
VERSION_MINOR = 2
VERSION_PATCH = 0

# Build metadata (optional)
VERSION_BUILD = None  # e.g., "beta.1", "rc.2", commit hash


def get_version() -> str:
    """Get the full version string."""
    if VERSION_BUILD:
        return f"{__version__}+{VERSION_BUILD}"
    return __version__


def get_version_info() -> dict:
    """Get version as a dictionary."""
    return {
        "version": __version__,
        "major": VERSION_MAJOR,
        "minor": VERSION_MINOR,
        "patch": VERSION_PATCH,
        "build": VERSION_BUILD,
        "full": get_version(),
    }
