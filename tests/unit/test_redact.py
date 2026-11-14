from __future__ import annotations

from omv_mcp.rpc.redact import redact, redact_text


def test_redacts_secret_keys_recursively() -> None:
    data = {
        "name": "share",
        "password": "hunter2",
        "nested": [{"api_key": "abc"}, {"token": "xyz"}],
        "mysql_root_password": "rootpw",
    }
    out = redact(data)
    assert out["name"] == "share"
    assert out["password"] == "***"
    assert out["nested"][0]["api_key"] == "***"
    assert out["nested"][1]["token"] == "***"
    assert out["mysql_root_password"] == "***"


def test_redacts_text_credentials_and_env_style() -> None:
    text = "postgres://user:pass@db/app MYSQL_ROOT_PASSWORD=rootpw secret: xyz"
    out = redact_text(text)
    assert "pass@" not in out
    assert "rootpw" not in out
    assert "xyz" not in out


def test_redacts_private_key_but_not_public() -> None:
    private = "-----BEGIN RSA PRIVATE KEY-----\nAAAA\n-----END RSA PRIVATE KEY-----"
    public_ssh = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAI tester@host"
    certificate = "-----BEGIN CERTIFICATE-----\nAAAA\n-----END CERTIFICATE-----"
    assert "AAAA" not in redact_text(private)
    assert public_ssh in redact_text(public_ssh)
    assert certificate in redact_text(certificate)


def test_redacts_all_string_values() -> None:
    assert redact({"command": "echo password=abc"})["command"] == "echo password=***"


def test_redacts_camel_case_omv_keys() -> None:
    data = {
        "privatekeyserver": "PRIV",
        "presharedkeyclient": "PSK",
        "apikey": "KEY",
    }
    assert redact(data) == {
        "privatekeyserver": "***",
        "presharedkeyclient": "***",
        "apikey": "***",
    }
    assert "PRIV" not in redact_text("privatekeyserver=PRIV")


def test_redacts_json_and_xml_secret_text() -> None:
    assert redact_text('{"password": "abc"}') == '{"password": "***"}'
    assert redact_text("<privatekeyserver>PRIV</privatekeyserver>") == (
        "<privatekeyserver>***</privatekeyserver>"
    )
