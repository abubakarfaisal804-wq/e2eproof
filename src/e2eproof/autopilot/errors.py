from ..errors import E2EProofError


class AutopilotError(E2EProofError):
    """Raised when the dry-run control plane cannot proceed safely."""
