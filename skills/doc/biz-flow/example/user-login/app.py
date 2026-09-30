"""完整 biz-flow 用户登录示例的源代码。"""


class FastAPI:
    def post(self, path: str):
        def decorator(function):
            return function

        return decorator


class LoginError(Exception):
    pass


app = FastAPI()
ACCOUNTS_TABLE = {
    "member@example.test": {
        "id": "account-1",
        "email": "member@example.test",
        "password_hash": "hash:correct-password",
        "disabled": False,
    },
}
SESSIONS_TABLE = {}


def query_account_by_email(email: str):
    if email in ACCOUNTS_TABLE:
        return ACCOUNTS_TABLE[email]
    return None


def write_account(account: dict):
    if account["email"] in ACCOUNTS_TABLE:
        raise LoginError("DUP")
    ACCOUNTS_TABLE[account["email"]] = account
    return account


def exchange_oauth_code(code: str, redirect_uri: str):
    if redirect_uri != "https://client.example.test/oauth/callback":
        raise LoginError("REDIRECT_URI")
    return {"access_token": "provider-token", "provider_user_id": "oauth-user-1"}


def read_oauth_userinfo(access_token: str):
    return {"email": "oauth@example.test", "display_name": "OAuth User"}


def issue_session(account: dict):
    token = {"access_token": "application-token", "account_id": account["id"]}
    SESSIONS_TABLE[account["id"]] = token
    return token


def compare_password_hash(account: dict, password: str) -> bool:
    return account["password_hash"] == "hash:" + password


def load_or_create_account(identity: dict, new_identity: bool) -> dict:
    email = identity["email"]
    account = query_account_by_email(email)
    if account:
        if new_identity:
            raise LoginError("DUP")
        return account
    return write_account({
        "id": "account-new",
        "email": email,
        "password_hash": "",
        "disabled": False,
    })


def finish_login(account: dict) -> dict:
    if account["disabled"] is True:
        return {"status": 403, "error": "OFF"}
    try:
        session = issue_session(account)
    except LoginError as error:
        return {"status": 403, "error": str(error)}
    return {"status": 200, "data": session}


# @business: 密码登录与会话建立
@app.post("/auth/password-login")
def password_login(request: dict) -> dict:
    account = query_account_by_email(request["email"])
    if not account:
        return {"status": 401, "error": "ACCOUNT_NOT_FOUND"}
    if not compare_password_hash(account, request["password"]):
        return {"status": 401, "error": "PASSWORD_INVALID"}
    return finish_login(account)


# @business: OAuth2 登录与账号绑定
@app.post("/auth/oauth2-login")
def oauth2_login(request: dict) -> dict:
    try:
        if request["code"] == "expired-code":
            raise LoginError("EXPIRED")
        if request["code"] == "provider-down":
            raise LoginError("DOWN")
        if request["state"] != "valid-state":
            raise LoginError("STATE")
        grant = exchange_oauth_code(request["code"], request["redirect_uri"])
        if request["provider_token"] == "invalid-provider-token":
            raise LoginError("UNAUTH")
        identity = read_oauth_userinfo(grant["access_token"])
        account = load_or_create_account(identity, request["new_identity"])
    except LoginError as error:
        return {"status": 401, "error": str(error)}
    return finish_login(account)
