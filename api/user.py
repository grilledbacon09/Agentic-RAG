from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator
from services import auth
from services.users import search_medications, validate_medications
from repositories.users import profile, replace_profile

router = APIRouter(prefix='/api')

class Medication(BaseModel):
    model_config = ConfigDict(extra='forbid')
    drug_id: str = Field(pattern=r'^[0-9]{9}$')
    name: str = Field(default='', max_length=300)

class ProfileUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    gender: Literal['male', 'female', 'other', 'unspecified'] = 'unspecified'
    age: int | None = Field(default=None, ge=0, le=120, strict=True)
    allergy_status: Literal['unknown', 'none', 'known']
    medication_status: Literal['unknown', 'none', 'known']
    allergies: list[str] = Field(default_factory=list, max_length=50)
    medications: list[Medication] = Field(default_factory=list, max_length=50)
    version: int = Field(ge=1)

    @model_validator(mode='after')
    def consistent(self):
        self.allergies = [name.strip() for name in self.allergies]
        if any(not name or len(name) > 200 for name in self.allergies):
            raise ValueError('알레르기는 빈 값 없이 항목당 200자까지 입력해주세요.')
        if len(set(x.casefold() for x in self.allergies)) != len(self.allergies):
            raise ValueError('중복 알레르기를 제거해주세요.')
        if len({m.drug_id for m in self.medications}) != len(self.medications):
            raise ValueError('중복 복용약을 제거해주세요.')
        for status, values in [(self.allergy_status, self.allergies), (self.medication_status, self.medications)]:
            if (status == 'known') != bool(values):
                raise ValueError('항목이 있으면 있음, 비어 있으면 없음 또는 미입력을 선택해주세요.')
        return self

class DeleteAccount(BaseModel):
    password: str = Field(min_length=1, max_length=128)

class ConsentUpdate(BaseModel):
    consents: dict[str, str]

@router.post('/users/me/consents', status_code=204)
def renew_consents(body: ConsentUpdate, member=Depends(auth.current_member)):
    from api.auth import POLICY_VERSION, POLICIES
    from uuid import uuid4
    if body.consents != {key: POLICY_VERSION for key in POLICIES}:
        raise HTTPException(422, '현재 동의 버전을 확인해주세요.')
    with auth.member_transaction(member) as cursor:
        for kind, version in body.consents.items():
            cursor.execute('''INSERT INTO app.user_consents(id,user_id,consent_type,policy_version,accepted_at)
                VALUES (%s,%s,%s,%s,now()) ON CONFLICT (user_id,consent_type,policy_version)
                DO UPDATE SET accepted_at=now(),withdrawn_at=NULL''',
                (str(uuid4()), member.user_id, kind, version))
    return Response(status_code=204)

@router.get('/users/me/profile')
def get_profile(member=Depends(auth.current_member)):
    with auth.member_transaction(member) as cursor:
        return profile(cursor, member.user_id)

@router.put('/users/me/profile')
def put_profile(body: ProfileUpdate, member=Depends(auth.current_member)):
    medications = validate_medications(body.medications)
    with auth.member_transaction(member) as cursor:
        return replace_profile(cursor, member.user_id, body, medications)

@router.get('/users/me/medications/search')
def medications_search(q: str = Query(min_length=1, max_length=200), member=Depends(auth.current_member)):
    return {'items': search_medications(q)}

@router.delete('/users/me', status_code=204)
def delete_account(body: DeleteAccount, request: Request, member=Depends(auth.current_member)):
    auth.rate_limit(request, member.user_id, 'delete_account')
    with auth.member_transaction(member) as cursor:
        cursor.execute('SELECT password_hash FROM app.users WHERE id=%s', (member.user_id,))
        if not auth.verify_password(cursor.fetchone()['password_hash'], body.password):
            raise HTTPException(401, '비밀번호가 올바르지 않습니다.')
        cursor.execute('INSERT INTO app.deleted_users(user_id) VALUES (%s)', (member.user_id,))
        cursor.execute('DELETE FROM app.users WHERE id=%s', (member.user_id,))
    response = Response(status_code=204)
    auth.clear_cookie(response)
    response.delete_cookie('user_id', path='/')
    return response

@router.api_route('/user/setting', methods=['POST'])
@router.api_route('/user/setting/{user_id}', methods=['GET'])
def legacy_setting(user_id: str = ''):
    raise HTTPException(410, '이전 설정 API가 종료되었습니다. 로그인 후 설정을 이용해주세요.')
