from dotenv import load_dotenv

load_dotenv()

import json
import os
from langsmith import Client

client = Client()

DATASETS = {
    "dealforge-router": "langsmith/dataset/dealforge_router_dataset.json",
    "dealforge-memory": "langsmith/dataset/dealforge_memory_dataset.json",
    "dealforge-analytics": "langsmith/dataset/dealforge_analytics_dataset.json",
    # "dealforge-rag": "langsmith/rag.json",
    # "dealforge-approval": "langsmith/approval.json",
}


def get_or_create_dataset(name):
    datasets = client.list_datasets()
    for d in datasets:
        if d.name == name:
            return d
    return client.create_dataset(dataset_name=name)


for dataset_name, file_path in DATASETS.items():

    dataset = get_or_create_dataset(dataset_name)

    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    for item in data:
        client.create_example(
            dataset_id=dataset.id,
            inputs={"input": item["input"]},
            outputs={
                "expected_tool": item.get("expected_tool"),
                "expected_intent": item.get("expected_intent"),
                "expected_output_type": item.get("expected_output_type"),
            },
        )

    print(f"Uploaded {len(data)} → {dataset_name}")
