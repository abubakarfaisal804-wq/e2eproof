class E2EProofError(Exception):
    """Base error for expected E2EProof failures."""


class ContractError(E2EProofError):
    """The contract is invalid or unsafe."""


class StepExecutionError(E2EProofError):
    """A verification step failed."""


class EvidenceVerificationError(E2EProofError):
    """An evidence bundle failed integrity verification."""


class AIError(E2EProofError):
    """The optional OpenAI integration failed."""
