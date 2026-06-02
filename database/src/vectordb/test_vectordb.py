"""
n_results: 너무 적으면 충분한 정보를 못 얻고, 너무 많으면 LLM의 토큰 제한에 걸립니다. 보통 3~5개가 적당합니다.
Distance(거리): results['distances'] 값을 확인해 보세요. 이 값이 작을수록 유사도가 높다는 뜻입니다. (보통 1.0 이상이면 관련성이 낮다고 판단할 수 있습니다.)
"""

import chromadb
import create_vectordb

# 1. 클라이언트 연결
client = chromadb.HttpClient(host='localhost', port=8000)

# 2. 컬렉션 가져오기
collection = client.get_collection(name="medical_knowledge",
                                   embedding_function=create_vectordb.e5_embedding_function)

sample = collection.get(limit=3)
print(sample['documents'])

# 컬렉션 목록 확인
print(client.list_collections())

# 문서 수 확인
print(collection.count())


# 3. 쿼리 실행
print("\n===== vectorDB test =====\n")
user_query = input("질문: ")

query = f"query: {user_query}"
results = collection.query(
    query_texts=[query],
    n_results=5
)

# 4. 결과 출력
for i, dist in enumerate(results['distances'][0]):
    print(i, dist)

top_distance = results['distances'][0]



print("\n===== 검색 결과 =====\n")

for i in range(len(results['ids'][0])):

    distance = results['distances'][0][i]

    print(f"순위: {i+1}")
    print(f"ID: {results['ids'][0][i]}")
    print(f"거리: {distance}")

    print(
        f"메타데이터: "
        f"{results['metadatas'][0][i]}"
    )

    print(
        f"내용:\n"
        f"{results['documents'][0][i][:300]}"
    )

    print("-" * 50)

# valid_indices = [
#     idx for idx, dist in enumerate(results['distances'][0])
#     if dist <= top_distance + 0.15
# ]
# for i in valid_indices:
#     print(f"순위: {i+1}")
#     print(f"ID: {results['ids'][0][i]}")
#     print(f"[내용] {results['documents'][0][i][:200]}...") # 100자만 출력
#     print(f"거리: {results['distances']}")
#     print(f"메타데이터: {results['metadatas'][0][i]}")
#     print("-" * 30)
    