from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from veripy.main import cli


def test_regen_flag_accepted():
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert "--regen" in result.output


def test_llm_add_proof_calls_anthropic():
    from veripy.main import _llm_add_proof

    mock_client = MagicMock()
    mock_client.messages.create.return_value = MagicMock(content=[MagicMock(text="method f() {}")])
    with patch("anthropic.Anthropic", return_value=mock_client):
        result = _llm_add_proof("method f() {}", "error: postcondition")
        assert "method f()" in result
        mock_client.messages.create.assert_called_once()
