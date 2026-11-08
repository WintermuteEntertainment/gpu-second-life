# Sends this PC's public SSH key to the Mint session on Noodlecart. Asks for the Mint password.
Get-Content "$env:USERPROFILE\.ssh\id_ed25519.pub" | ssh -o UserKnownHostsFile=NUL -o StrictHostKeyChecking=accept-new mint@192.168.2.51 "mkdir -p ~/.ssh && chmod 700 ~/.ssh && cat >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys && echo KEY_INSTALLED"
