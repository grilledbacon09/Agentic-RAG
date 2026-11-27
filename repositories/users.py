from uuid import uuid4


def profile(cursor, user_id):
    cursor.execute('SELECT gender,age,age_recorded_at,allergy_status,medication_status,version FROM app.user_profiles WHERE user_id=%s', (user_id,))
    result = dict(cursor.fetchone())
    cursor.execute('SELECT name FROM app.user_allergies WHERE user_id=%s ORDER BY name_normalized', (user_id,))
    result['allergies'] = [r['name'] for r in cursor.fetchall()]
    cursor.execute('SELECT drug_id,name FROM app.user_medications WHERE user_id=%s ORDER BY name,drug_id', (user_id,))
    result['medications'] = [dict(r) for r in cursor.fetchall()]
    return result


def replace_profile(cursor, user_id, body, medications):
    cursor.execute('''UPDATE app.user_profiles SET gender=%s, age=%s,
        age_recorded_at=CASE WHEN %s IS NULL THEN NULL ELSE now() END,
        allergy_status=%s,medication_status=%s,version=version+1
        WHERE user_id=%s AND version=%s RETURNING version''',
        (body.gender, body.age, body.age, body.allergy_status, body.medication_status, user_id, body.version))
    if not cursor.fetchone():
        from fastapi import HTTPException
        raise HTTPException(409, '다른 화면에서 설정이 변경되었습니다. 최신 설정을 불러와 다시 편집해주세요.')
    cursor.execute('DELETE FROM app.user_allergies WHERE user_id=%s', (user_id,))
    cursor.execute('DELETE FROM app.user_medications WHERE user_id=%s', (user_id,))
    for name in body.allergies:
        cursor.execute('INSERT INTO app.user_allergies(id,user_id,name,name_normalized) VALUES (%s,%s,%s,%s)',
            (str(uuid4()), user_id, name, name.strip().casefold()))
    for med in medications:
        cursor.execute('INSERT INTO app.user_medications(id,user_id,drug_id,name) VALUES (%s,%s,%s,%s)',
            (str(uuid4()), user_id, med['drug_id'], med['name']))
    return profile(cursor, user_id)
