from tenet_harness.integrations.secrets import KeyringSecrets as _Keyring, MemorySecrets, SecretStore  # noqa: F401


class KeyringSecrets(_Keyring):
    """Windows Credential Manager entries for this application."""

    def __init__(self, service: str = "SecondBrain"):
        super().__init__(service)
