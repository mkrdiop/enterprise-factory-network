"""Domain-facing repository operations; callers own the transaction."""
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from .models import Publisher, Factory, ArtifactBlob, ArtifactLocation, FactoryRelease

class RegistryConflict(Exception): pass
class RegistryNotFound(Exception): pass

def _flush(session,message):
    try: session.flush()
    except IntegrityError as exc: raise RegistryConflict(message) from exc

class PublisherRepository:
    def __init__(self,session): self.s=session
    def get(self,uri): return self.s.scalar(select(Publisher).where(Publisher.publisher_uri==uri))
    def create(self,uri):
        row=Publisher(publisher_uri=uri); self.s.add(row); _flush(self.s,"publisher URI already claimed"); return row
    def retire(self,uri):
        row=self.get(uri)
        if row is None: raise RegistryNotFound(uri)
        if row.lifecycle_state=="active": row.lifecycle_state="retired"; row.retired_at=datetime.now(timezone.utc); self.s.flush()
        return row

class FactoryRepository:
    def __init__(self,session): self.s=session
    def get(self,uri,factory_id):
        return self.s.scalar(select(Factory).join(Publisher).where(Publisher.publisher_uri==uri,Factory.factory_id==factory_id))
    def create(self,uri,factory_id):
        pub=PublisherRepository(self.s).get(uri)
        if pub is None: raise RegistryNotFound(uri)
        if pub.lifecycle_state!="active": raise RegistryConflict("retired publisher cannot register a Factory")
        row=Factory(publisher_record_id=pub.publisher_record_id,factory_id=factory_id); self.s.add(row); _flush(self.s,"publisher-scoped Factory identity already exists"); return row
    def retire(self,uri,factory_id):
        row=self.get(uri,factory_id)
        if row is None: raise RegistryNotFound(f"{uri}/{factory_id}")
        if row.lifecycle_state=="active": row.lifecycle_state="retired"; row.retired_at=datetime.now(timezone.utc); self.s.flush()
        return row

class ReleaseRepository:
    def __init__(self,session): self.s=session
    def get(self,uri,factory_id,version):
        return self.s.scalar(select(FactoryRelease).join(Factory).join(Publisher).where(Publisher.publisher_uri==uri,Factory.factory_id==factory_id,FactoryRelease.version==version))
    def publish(self,uri,factory_id,version,profile,algorithm,digest,length,provider,key,published_at):
        factory=FactoryRepository(self.s).get(uri,factory_id)
        if factory is None: raise RegistryNotFound(f"{uri}/{factory_id}")
        if factory.lifecycle_state!="active": raise RegistryConflict("retired Factory cannot publish releases")
        blob=self.s.scalar(select(ArtifactBlob).where(ArtifactBlob.digest_profile==profile,ArtifactBlob.digest_algorithm==algorithm,ArtifactBlob.digest_value==digest))
        if blob is None:
            blob=ArtifactBlob(digest_profile=profile,digest_algorithm=algorithm,digest_value=digest,byte_length=length); self.s.add(blob); _flush(self.s,"artifact digest tuple already exists; retry after reading")
        elif blob.byte_length!=length: raise RegistryConflict("digest tuple byte length mismatch")
        location=self.s.scalar(select(ArtifactLocation).where(ArtifactLocation.provider==provider,ArtifactLocation.object_key==key))
        if location is None:
            self.s.add(ArtifactLocation(artifact_blob_id=blob.artifact_blob_id,provider=provider,object_key=key)); _flush(self.s,"artifact location already registered")
        elif location.artifact_blob_id!=blob.artifact_blob_id: raise RegistryConflict("object key already maps to another digest")
        row=FactoryRelease(factory_record_id=factory.factory_record_id,version=version,digest_profile=profile,digest_algorithm=algorithm,digest_value=digest,artifact_blob_id=blob.artifact_blob_id,published_at=published_at)
        self.s.add(row); _flush(self.s,"Factory release version already exists or digest tuple mismatches"); return row
