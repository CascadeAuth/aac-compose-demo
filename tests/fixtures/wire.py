"""Test-only AAC v1 wire fixture using CLI-issued keys and public cryptography.

This deliberately bypasses the sender guard. It is not an SDK or business-agent
dependency. Positive controls travel through the same receiver as each attack.
Only the CLI's Ed25519 development identity profile is needed by this fixture.
"""
import base64
import hashlib
import hmac
import json
import struct
import time
import uuid
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def b64(value):
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def lp(value, width):
    value = value.encode()
    return len(value).to_bytes(width, "big") + value


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def chain(origin, booking, root_key, task, return_amount=None):
    now = int(time.time())
    root = (lp(origin["tenant_id"], 2) + lp(digest("simulated-Marc-approval-" + task), 1)
            + lp(digest(origin["workload_spiffe_id"]), 1) + lp(origin["root_key_id"], 2)
            + lp("Ed25519", 1) + struct.pack(">QH", now, 0))
    key = serialization.load_pem_private_key(Path(root_key).read_bytes(), None)
    assert isinstance(key, Ed25519PrivateKey), "Fixture uses CLI-issued Ed25519 material"
    root_signature = key.sign(root)
    key.public_key().verify(root_signature, root)
    caveats = [
        (f"action:reserve_travel,amount_max:10000,originator_reference:PO #4143,task_ref:{task},valid_until:{now+7200}",
         origin["workload_spiffe_id"], origin["workload_spiffe_id"]),
        (f"amount_max:8000,valid_until:{now+1800}", origin["workload_spiffe_id"], booking["workload_spiffe_id"]),
    ]
    if return_amount is not None:
        caveats.append((f"amount_max:{return_amount},valid_until:{now+300}",
                        booking["workload_spiffe_id"], origin["workload_spiffe_id"]))
    encoded = [lp(predicates, 4) + lp(digest(creator), 1) + lp(audience, 2)
               for predicates, creator, audience in caveats]
    signature = root_signature
    for caveat in encoded:
        signature = hmac.new(signature, caveat, hashlib.sha256).digest()
    wire = (b"\x01\x00" + root + struct.pack(">H", len(root_signature)) + root_signature
            + struct.pack(">H", len(encoded)) + b"".join(encoded) + signature)
    return b64(wire), hashlib.sha256(root_signature).hexdigest()


def proof(token, key_file, cert_file, target):
    now = int(time.time())
    key = serialization.load_pem_private_key(Path(key_file).read_bytes(), None)
    assert isinstance(key, Ed25519PrivateKey)
    cert = x509.load_pem_x509_certificate(Path(cert_file).read_bytes())
    header = {"alg": "EdDSA", "typ": "aac-dpop+jwt",
              "x5c": [base64.b64encode(cert.public_bytes(serialization.Encoding.DER)).decode()]}
    claims = {"htm": "POST", "htu": target, "iat": now, "exp": now + 60,
              "jti": str(uuid.uuid4()), "ath": b64(hashlib.sha256(token.encode()).digest())}
    signing = b64(json.dumps(header).encode()) + "." + b64(json.dumps(claims).encode())
    signature = key.sign(signing.encode())
    cert.public_key().verify(signature, signing.encode())
    return signing + "." + b64(signature)
