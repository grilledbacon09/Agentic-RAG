from contextlib import contextmanager

from fastapi import APIRouter, HTTPException, Path, Query

from services.medicines import MedicineDatabaseUnavailable, medicine_repository

router = APIRouter(prefix='/api')


@contextmanager
def get_repository():
    try:
        with medicine_repository() as repository:
            yield repository
    except MedicineDatabaseUnavailable:
        raise HTTPException(status_code=503, detail={
            'code': 'MEDICINE_DATABASE_UNAVAILABLE',
            'message': '약품 정보 서버에 연결할 수 없습니다. 잠시 후 다시 시도해주세요.',
        }) from None


@router.get('/medicines')
def get_medicines(
    search: str = Query(default='', max_length=200),
    limit: int = Query(default=20, ge=1, le=50),
    offset: int = Query(default=0, ge=0, le=100000),
):
    with get_repository() as repository:
        return repository.search(search.strip(), limit, offset)


@router.get('/medicines/{item_seq}')
def get_medicine(
    item_seq: str = Path(pattern=r'^\d{9}$'),
):
    with get_repository() as repository:
        medicine = repository.detail(item_seq)
    if medicine is None:
        raise HTTPException(status_code=404, detail={
            'code': 'MEDICINE_NOT_FOUND', 'message': '해당 약품 정보를 찾을 수 없습니다.',
        })
    return medicine
