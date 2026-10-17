"""
Migration script to tag existing documents and Qdrant points with tenant metadata.
Sets tenant_id='global', visibility='public', owner_id='system' for pre-existing documents and chunks.
"""
import os
import sqlite3
from qdrant_client import QdrantClient, models

def migrate_sqlite():
    db_path = "data/processed/documents.sqlite"
    if not os.path.exists(db_path):
        print(f"SQLite DB not found at {db_path}")
        return
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(documents)")
    cols = [r[1] for r in cursor.fetchall()]
    print("SQLite columns:", cols)

    # In case columns weren't added yet, run alter table
    for col, col_def in [
        ("tenant_id", "TEXT NOT NULL DEFAULT 'global'"),
        ("owner_id", "TEXT"),
        ("visibility", "TEXT NOT NULL DEFAULT 'tenant'"),
    ]:
        if col not in cols:
            print(f"Adding column {col} to documents...")
            cursor.execute(f"ALTER TABLE documents ADD COLUMN {col} {col_def}")

    cursor.execute(
        "UPDATE documents SET tenant_id = 'global', visibility = 'public'"
    )
    conn.commit()

    cursor.execute("SELECT doc_id, tenant_id, owner_id, visibility FROM documents LIMIT 5")
    rows = cursor.fetchall()
    print("Updated sample docs in SQLite:")
    for r in rows:
        print(" ", r)
    conn.close()

def migrate_qdrant():
    url = os.getenv("QDRANT_URL", "http://localhost:6333")
    try:
        client = QdrantClient(url=url)
        collections = [c.name for c in client.get_collections().collections]
        print("Found Qdrant collections:", collections)
    except Exception as e:
        print(f"Could not connect to Qdrant at {url}: {e}")
        return

    for col in collections:
        print(f"\nProcessing collection: {col}")
        # Create payload indexes if not exist
        for field in ["tenant_id", "owner_id", "visibility"]:
            try:
                client.create_payload_index(
                    collection_name=col,
                    field_name=field,
                    field_schema=models.PayloadSchemaType.KEYWORD
                )
                print(f"Created/verified index on '{field}' in {col}")
            except Exception as e:
                print(f"Index on '{field}' note: {e}")

        # Update all existing points with tenant_id='global', visibility='public', owner_id='system'
        try:
            client.set_payload(
                collection_name=col,
                payload={
                    "tenant_id": "global",
                    "visibility": "public",
                    "owner_id": "system"
                },
                points=models.Filter(must=[])
            )
            count = client.count(collection_name=col).count
            print(f"Tagged {count} points in {col} with tenant_id='global', visibility='public'")
        except Exception as e:
            print(f"Error setting payload in {col}: {e}")

if __name__ == "__main__":
    print("Migrating SQLite...")
    migrate_sqlite()
    print("\nMigrating Qdrant...")
    migrate_qdrant()
    print("\nMigration completed successfully.")
