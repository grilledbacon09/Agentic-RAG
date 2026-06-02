import chromadb
from chromadb.utils import embedding_functions
from chromadb.config import Settings

import torch
import torch.nn.functional as F

from transformers import AutoModel, AutoTokenizer


class MultilingualE5EmbeddingFunction(
    embedding_functions.EmbeddingFunction
):
    def __init__(
        self,
        model_name="intfloat/multilingual-e5-base"
    ):
        self.tokenizer = AutoTokenizer.from_pretrained(model_name)

        self.model = AutoModel.from_pretrained(model_name)

        self.device = (
            "cuda"
            if torch.cuda.is_available()
            else "cpu"
        )

        self.model.to(self.device)
        self.model.eval()

    def average_pool(
        self,
        last_hidden_states,
        attention_mask
    ):
        last_hidden = last_hidden_states.masked_fill(
            ~attention_mask[..., None].bool(),
            0.0
        )

        return (
            last_hidden.sum(dim=1)
            / attention_mask.sum(dim=1)[..., None]
        )

    def __call__(self, input):

        all_embeddings = []

        micro_batch_size = 8

        for i in range(0, len(input), micro_batch_size):

            batch = input[i:i + micro_batch_size]

            processed_input = [
                text if (text.startswith("query:") or text.startswith("passage:"))
                    else f"passage: {text}"
                    for text in batch
            ]
    
            batch_dict = self.tokenizer(
                processed_input,
                max_length=256,
                padding=True,
                truncation=True,
                return_tensors="pt"
            ).to(self.device)

            with torch.no_grad():
                outputs = self.model(**batch_dict)

            embeddings = self.average_pool(
                outputs.last_hidden_state,
                batch_dict["attention_mask"]
            )

            embeddings = F.normalize(
                embeddings,
                p=2,
                dim=1
            )

            all_embeddings.extend(
                embeddings.cpu().numpy().tolist()
            )

        return all_embeddings


client = chromadb.HttpClient(
    host='localhost',
    port=8000,
    settings=Settings(
        allow_reset=True,
        anonymized_telemetry=False
    )
)

e5_embedding_function = MultilingualE5EmbeddingFunction()  # ← 이것만 전역에 남김

def init_collection():
    """명시적으로 호출할 때만 컬렉션 초기화"""
    try:
        client.delete_collection("medical_knowledge")
    except:
        pass
    return client.create_collection(
        name="medical_knowledge",
        embedding_function=e5_embedding_function,
        metadata={"hnsw:space": "cosine"}
    )

if __name__ == "__main__":
    init_collection()
    print(f"Server Heartbeat: {client.heartbeat()}")