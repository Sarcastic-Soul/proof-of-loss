"""AgentCore Runtime entrypoint (the CodeZip build runs this file)."""

from proof_of_loss.app import app

if __name__ == "__main__":
    app.run()
