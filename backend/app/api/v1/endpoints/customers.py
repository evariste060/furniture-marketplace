import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.v1.responses import (
    AUTHENTICATED,
    ERR,
    NOT_FOUND_404,
    VALIDATION_422,
    ResponseMap,
)
from app.core.dependencies import get_current_user
from app.core.request_context import RequestContext, get_request_context
from app.db.session import get_db
from app.models.identity import User
from app.schemas.address import (
    AddressCreateRequest,
    AddressResponse,
    AddressUpdateRequest,
)
from app.schemas.auth import MessageResponse
from app.schemas.customer import (
    CustomerProfileResponse,
    CustomerUpdateRequest,
)
from app.services.address_service import AddressService
from app.services.customer_service import CustomerService

router = APIRouter(prefix="/customers", tags=["Customer Accounts & Addresses"])

CONFLICT_409: ResponseMap = {
    409: {**ERR, "description": "Concurrent change to the address list; retry"}
}


@router.get(
    "/me",
    response_model=CustomerProfileResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve customer account profile",
    description="Returns profile information for the authenticated user.",
    responses={**AUTHENTICATED},
)
def get_profile(
    current_user: Annotated[User, Depends(get_current_user)],
) -> CustomerProfileResponse:
    profile = CustomerService.get_profile(current_user)
    return CustomerProfileResponse.from_user(profile)


@router.patch(
    "/me",
    response_model=CustomerProfileResponse,
    status_code=status.HTTP_200_OK,
    summary="Update customer profile details",
    description=(
        "Updates full name and/or phone number. Any other field (role, email, status) is "
        "rejected with 422."
    ),
    responses={
        **AUTHENTICATED,
        409: {**ERR, "description": "Phone number already in use by another account"},
        **VALIDATION_422,
    },
)
def update_profile(
    req: CustomerUpdateRequest,
    ctx: Annotated[RequestContext, Depends(get_request_context)],
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> CustomerProfileResponse:
    updated = CustomerService.update_profile(db=db, user=current_user, req=req, ctx=ctx)
    return CustomerProfileResponse.from_user(updated)


@router.post(
    "/me/addresses",
    response_model=AddressResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new saved delivery address",
    description=(
        "Saves a delivery address for the authenticated customer. The first address always "
        "becomes the default; is_default=true moves the default to the new address."
    ),
    responses={**AUTHENTICATED, **CONFLICT_409, **VALIDATION_422},
)
def create_address(
    req: AddressCreateRequest,
    ctx: Annotated[RequestContext, Depends(get_request_context)],
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> AddressResponse:
    address = AddressService.create_address(db=db, user=current_user, req=req, ctx=ctx)
    return AddressResponse.model_validate(address)


@router.get(
    "/me/addresses",
    response_model=list[AddressResponse],
    status_code=status.HTTP_200_OK,
    summary="List customer saved delivery addresses",
    description="Returns the caller's saved addresses, default first.",
    responses={**AUTHENTICATED},
)
def list_addresses(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[AddressResponse]:
    addresses = AddressService.list_addresses(db=db, user=current_user)
    return [AddressResponse.model_validate(a) for a in addresses]


@router.get(
    "/me/addresses/{address_id}",
    response_model=AddressResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve single saved delivery address",
    description="Returns 404 for addresses that belong to other customers.",
    responses={**AUTHENTICATED, **NOT_FOUND_404, **VALIDATION_422},
)
def get_address(
    address_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> AddressResponse:
    address = AddressService.get_address(db=db, address_id=address_id, user=current_user)
    return AddressResponse.model_validate(address)


@router.put(
    "/me/addresses/{address_id}",
    response_model=AddressResponse,
    status_code=status.HTTP_200_OK,
    summary="Update single saved delivery address (partial)",
    description=(
        "Partial update: only fields present in the body change. is_default=false on the "
        "current default is rejected (422) because a default is always required. Returns 404 "
        "for addresses that belong to other customers."
    ),
    responses={**AUTHENTICATED, **NOT_FOUND_404, **CONFLICT_409, **VALIDATION_422},
)
def update_address(
    address_id: uuid.UUID,
    req: AddressUpdateRequest,
    ctx: Annotated[RequestContext, Depends(get_request_context)],
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> AddressResponse:
    updated = AddressService.update_address(
        db=db, address_id=address_id, user=current_user, req=req, ctx=ctx
    )
    return AddressResponse.model_validate(updated)


@router.delete(
    "/me/addresses/{address_id}",
    response_model=MessageResponse,
    status_code=status.HTTP_200_OK,
    summary="Delete saved delivery address",
    description=(
        "Deletes an owned address. If it was the default, the most recently created remaining "
        "address becomes the default."
    ),
    responses={**AUTHENTICATED, **NOT_FOUND_404, **CONFLICT_409, **VALIDATION_422},
)
def delete_address(
    address_id: uuid.UUID,
    ctx: Annotated[RequestContext, Depends(get_request_context)],
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> MessageResponse:
    AddressService.delete_address(db=db, address_id=address_id, user=current_user, ctx=ctx)
    return MessageResponse(message="Delivery address deleted successfully.")


@router.post(
    "/me/addresses/{address_id}/default",
    response_model=AddressResponse,
    status_code=status.HTTP_200_OK,
    summary="Set address as default delivery address",
    description="Makes the owned address the default and clears the previous default atomically.",
    responses={**AUTHENTICATED, **NOT_FOUND_404, **CONFLICT_409, **VALIDATION_422},
)
def set_default_address(
    address_id: uuid.UUID,
    ctx: Annotated[RequestContext, Depends(get_request_context)],
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> AddressResponse:
    address = AddressService.set_default_address(
        db=db, address_id=address_id, user=current_user, ctx=ctx
    )
    return AddressResponse.model_validate(address)
