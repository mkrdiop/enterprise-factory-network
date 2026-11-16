#!/usr/bin/env node
// Independent verifier: Node built-in crypto; no project/Python code imported.
import { readFileSync } from "node:fs";
import { createHash, createPublicKey, verify } from "node:crypto";
const path = new URL("./fixtures/psi50-release-interoperability-v1.json", import.meta.url);
const f = JSON.parse(readFileSync(path, "utf8"));
function assertIJson(value, path="$") {
  if (typeof value === "number" && !Number.isFinite(value)) throw Error("EFS_JCS_INVALID_NUMBER " + path);
  if (typeof value === "string") for(let i=0;i<value.length;i++){const c=value.charCodeAt(i);if(c>=0xD800&&c<=0xDBFF){const n=value.charCodeAt(i+1);if(!(n>=0xDC00&&n<=0xDFFF))throw Error("EFS_JCS_INVALID_UNICODE "+path);i++;}else if(c>=0xDC00&&c<=0xDFFF)throw Error("EFS_JCS_INVALID_UNICODE "+path);}
  else if(Array.isArray(value)) value.forEach((v,i)=>assertIJson(v,path+"/"+i));
  else if(value&&typeof value==="object") Object.keys(value).forEach(k=>{assertIJson(k,path+"/<key>");assertIJson(value[k],path+"/"+k);});
}
const canonicalize=v=>{assertIJson(v);if(v===null||typeof v!=="object")return JSON.stringify(v);if(Array.isArray(v))return "["+v.map(canonicalize).join(",")+"]";return "{"+Object.keys(v).sort().map(k=>JSON.stringify(k)+":"+canonicalize(v[k])).join(",")+"}";};
const b64url=b=>Buffer.from(b).toString("base64url");
const decodeCanonical=(s,n)=>{if(!/^[A-Za-z0-9_-]+$/.test(s))throw Error("padded or non-Base64URL value");const b=Buffer.from(s,"base64url");if(b.length!==n||b64url(b)!==s)throw Error("non-canonical Base64URL or wrong decoded length");return b;};
function pointerParts(path){return path.split("/").slice(1).map(x=>x.replace(/~1/g,"/").replace(/~0/g,"~"));}
function applyPatch(document, operations){
 const root=document;
 for(const op of operations){
  const parts=pointerParts(op.path);let parent=root;
  for(const part of parts.slice(0,-1)) parent=parent[part];
  const key=parts[parts.length-1];
  if(op.op==="replace"){if(Array.isArray(parent))parent[Number(key)]=op.value;else parent[key]=op.value;}
  else if(op.op==="add"){if(Array.isArray(parent)){if(key==="-")parent.push(op.value);else parent.splice(Number(key),0,op.value);}else parent[key]=op.value;}
  else throw Error("unsupported vector patch operation "+op.op);
 }
 return root;
}
function testNegativeVectors(){
 const set=JSON.parse(readFileSync(new URL("./signatures-v1.json",import.meta.url),"utf8"));
 const base=JSON.parse(readFileSync(new URL("./fixtures/psi50-release-interoperability-v1.json",import.meta.url),"utf8"));
 for(const v of set.vectors.filter(x=>x.kind==="negative")){
  if(v.base_fixture!=="tests/conformance/fixtures/psi50-release-interoperability-v1.json"||!Array.isArray(v.patch)||!v.expected_failure)throw Error("incomplete executable negative vector "+v.id);
  const target=v.target==="manifest"?base.manifest:v.target==="envelope"?base.envelope:v.target==="resolver"?base.resolver:null;
  if(!target)throw Error("unknown mutation target "+v.target);
  applyPatch(JSON.parse(JSON.stringify(target)),v.patch);
 }
}
function testDetachedManifestProhibition(){
 const schema=JSON.parse(readFileSync(new URL("../../schemas/efs/v1/factory-manifest.schema.json",import.meta.url),"utf8"));
 const negative=JSON.parse(readFileSync(new URL("./fixtures/psi50-manifest-signature-forbidden-v1.json",import.meta.url),"utf8"));
 if(schema.$defs.release.properties.signature!==false)throw Error("manifest schema does not forbid release.signature");
 if(!Object.hasOwn(negative.manifest.release,"signature")||negative.expected.diagnostic_path!=="/release"||negative.expected.diagnostic_code!=="EFS_SCHEMA_CONSTRAINT")throw Error("detached manifest negative fixture is incomplete");
}
function testJcsVectors(){const vectors=JSON.parse(readFileSync(new URL("./signatures-v1.json",import.meta.url),"utf8")).jcs_vectors;for(const v of vectors){if(v.kind==="jcs-invalid"){let parsed;try{parsed=JSON.parse(v.raw_json);}catch{continue;}let code="";try{canonicalize(parsed);}catch(e){code=e.message.split(" ")[0];}if(code!==v.expected_failure)throw Error("JCS negative vector "+v.id+" expected "+v.expected_failure+" got "+code);}else if(canonicalize(v.input)!==v.expected_canonical)throw Error("JCS vector mismatch: "+v.id);}}
try {
 testJcsVectors();
 testNegativeVectors();
 testDetachedManifestProhibition();
 const m=JSON.parse(JSON.stringify(f.manifest)),s=f.envelope.statement,sig=f.envelope.signatures[0];
 if(Object.hasOwn(m.release,"signature"))throw Error("release.signature must be absent");
 if(m.publisher.id!==s.publisher_id||m.factory.id!==s.factory_id||m.release.version!==s.release_version||m.efsVersion!==s.efs_version)throw Error("manifest coordinate binding mismatch");
 const projection=JSON.parse(JSON.stringify(m));delete projection.release.digest;delete projection.release.signature;
 const digest=createHash("sha256").update(canonicalize({domain:"efs.factory-release.v1",manifest:projection}),"utf8").digest(),digestText=b64url(digest);
 if(digestText!==f.expected.release_digest_base64url||m.release.digest.value!==digestText||m.release.digest.algorithm!=="SHA-256"||m.release.digest.profile!=="efs-jcs-sha256-v1")throw Error("release digest KAT or manifest tuple mismatch");
 if(s.digest.profile_id!=="efs-jcs-sha256-v1"||s.digest.algorithm!=="SHA-256"||s.digest.value!==digestText)throw Error("envelope digest binding mismatch");
 if(f.resolver.publisher_id!==s.publisher_id||f.resolver.key_id!==sig.key_id||f.resolver.algorithm!==sig.algorithm||f.envelope.profile_id!=="efs-ed25519-jcs-v1")throw Error("resolver/profile binding mismatch");
 const signedObject={domain:"efs.release.signature.v1",signer:{algorithm:sig.algorithm,key_id:sig.key_id},statement:s};
 const preimage=Buffer.concat([Buffer.from("EFS-SIGNATURE-V1\n","ascii"),Buffer.from(canonicalize(signedObject),"utf8")]);
 const raw=decodeCanonical(f.resolver.public_key_base64url,32),signature=decodeCanonical(sig.signature,64);
 const key=createPublicKey({key:Buffer.concat([Buffer.from("302a300506032b6570032100","hex"),raw]),format:"der",type:"spki"});
 if(!verify(null,preimage,key,signature))throw Error("Ed25519 verification failed");
 console.log("PASS: RFC 8785 edge vectors, digest, detached placement, manifest/envelope binding, canonical encodings, Ed25519");
}catch(e){console.error("FAIL:",e.message);process.exitCode=1;}
