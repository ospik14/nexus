from fastapi import APIRouter, Depends, Request, Response

from ..auth import Identity, authenticated, check_origin
from ..schemas import LoginInput

router = APIRouter(prefix="/api/auth")


@router.post("/login", dependencies=[Depends(check_origin)])
def login(payload: LoginInput, request: Request, response: Response):
    return request.app.state.auth.login(
        payload.username, payload.password.get_secret_value(), response
    )


@router.get("/session")
def session(request: Request, identity: Identity = Depends(authenticated)):
    return {
        "username": request.app.state.settings.admin_name,
        "csrf": identity.csrf_token,
        "expires": identity.expires,
    }


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response, identity: Identity = Depends(authenticated)):
    request.app.state.auth.logout(identity, response)
