import botocore.tokens
import botocore.session
import botocore.compat
import botocore.exceptions
import dateutil.parser


class SSOTokenProviderWithoutProfile(botocore.tokens.SSOTokenProvider):
    """Ref: https://github.com/boto/botocore/blob/develop/botocore/tokens.py#L245"""

    def __init__(self, session_name: str):
        self._session_name = session_name
        super().__init__(botocore.session.Session())

    def _refresher(self):
        token_dict = self._token_loader(None, session_name=self._session_name)
        expiration = dateutil.parser.parse(token_dict["expiresAt"])

        remaining = botocore.compat.total_seconds(expiration - self._now())
        if remaining < self._REFRESH_WINDOW:
            new_token_dict = self._refresh_access_token(token_dict)
            if new_token_dict is not None:
                token_dict = new_token_dict
                expiration = token_dict["expiresAt"]
                self._token_loader.save_token(
                    None, token_dict, session_name=self._session_name
                )

        return botocore.tokens.FrozenAuthToken(
            token_dict["accessToken"], expiration=expiration
        )

    def _load_sso_config(self):
        loaded_config = self._session.full_config
        sso_sessions = loaded_config.get("sso_sessions", {})

        sso_config = sso_sessions.get(self._session_name, None)

        if not sso_config:
            error_msg = (
                f'The "{self._session_name}" sso_session configuration does not exist.'
            )
            raise botocore.exceptions.InvalidConfigError(error_msg=error_msg)

        return {
            "session_name": self._session_name,
            "sso_region": sso_config["sso_region"],
            "sso_start_url": sso_config["sso_start_url"],
        }
