# Infrastructure as Prompt in Codespaces

The app starts automatically and opens in a new browser tab. If it did not:

1. Open the **Ports** tab and click the globe icon next to port **3000**.
2. Still nothing? Run `bash .devcontainer/start.sh` in the terminal; logs are in `/tmp/iap-backend.log` and `/tmp/iap-frontend.log`.

Then choose **Start with this example** and follow the interview.

- Everything runs in **simulation mode**: Terraform plans use placeholder credentials and no AWS resources are created. Real deployment is disabled.
- The forwarded port is **private** to your GitHub account unless you change its visibility.
- The first validation downloads the AWS Terraform provider (about 100 MB), so it takes a few minutes; later runs are faster.
- Stop the codespace when you are done (Codespaces menu → *Stop current codespace*) to save your free usage.
