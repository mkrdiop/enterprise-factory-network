#!/usr/bin/env node
// Independent verifier: Node built-in crypto; no project/Python code imported.
import { readFileSync } from "node:fs";
import { createHash, createPublicKey, verify } from "node:crypto";
const path = new URL("./fixtures/psi50-release-interoperability-v1.json", import.meta.url);
const f = JSON.parse(readFileSync(path, "utf8"));
const canonicalize = (v) => {
  if (v === null || typeof v !== "object") return JSON.stringify(v);
  if (Array.isArray(v)) return "[" + v.map(canonicalize).join(",") + "]";
  return "{" + Object.keys(v).sort().map(k => JSON.stringify(k) + ":" + canonicalize(v[k])).join(",") + "}";
};
const b64url = b => Buffer.from(b).toString("base64url");
const decodeCanonical = (s,n) => {
  if (!/^[A-Za-z0-9_-]+$/.test(s)) throw Error("padded or non-Base64URL value");
  const b=Buffer.from(s,"base64url");
  if (b.length!==n || b64url(b)!==s) throw Error("non-canonical Base64URL or wrong decoded length");
  return b;
};
try {
 const m=structuredClone(f.manifest), s=f.envelope.statement, sig=f.envelope.signatures[0];
 if (Object.hasOwn(m.release,"signature")) throw Error("release.signature must be absent");
 if (m.publisher.id!==s.publisher_id || m.factory.id!==s.factory_id || m.release.version!==s.release_version || m.efsVersion!==s.efs_version) throw Error("manifest coordinate binding mismatch");
 const projection=structuredClone(m); delete projection.release.digest; delete projection.release.signature;
 const digest=createHash("sha256").update(canonicalize({domain:"efs.factory-release.v1",manifest:projection}),"utf8").digest();
 const digestText=b64url(digest);
 if (digestText!==f.expected.release_digest_base64url || m.release.digest.value!==digestText || m.release.digest.algorithm!=="SHA-256" || m.release.digest.profile!=="efs-jcs-sha256-v1") throw Error("release digest KAT or manifest tuple mismatch");
 if (s.digest.profile_id!=="efs-jcs-sha256-v1" || s.digest.algorithm!=="SHA-256" || s.digest.value!==digestText) throw Error("envelope digest binding mismatch");
 if (f.resolver.publisher_id!==s.publisher_id || f.resolver.key_id!==sig.key_id || f.resolver.algorithm!==sig.algorithm || f.envelope.profile_id!=="efs-ed25519-jcs-v1") throw Error("resolver/profile binding mismatch");
 const signedObject={domain:"efs.release.signature.v1",signer:{algorithm:sig.algorithm,key_id:sig.key_id},statement:s};
 const preimage=Buffer.concat([Buffer.from("EFS-SIGNATURE-V1\n","ascii"),Buffer.from(canonicalize(signedObject),"utf8")]);
 const raw=decodeCanonical(f.resolver.public_key_base64url,32), signature=decodeCanonical(sig.signature,64);
 const key=createPublicKey({key:Buffer.concat([Buffer.from("302a300506032b6570032100","hex"),raw]),format:"der",type:"spki"});
 if (!verify(null,preimage,key,signature)) throw Error("Ed25519 verification failed");
 console.log("PASS: digest, detached placement, manifest/envelope binding, canonical encodings, Ed25519");
} catch(e) { console.error("FAIL:",e.message); process.exitCode=1; }
