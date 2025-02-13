# How to Fork the Repository

Forking a repository is the first step towards contributing to our project. By creating a fork, you make an independent copy of the original repository in your own GitHub account. This allows you to freely experiment with changes without affecting the original codebase until you're ready to propose your contributions.

## Steps to fork

1. **Navigate to the repository:**
   - Go to the GitHub page of the original repository you want to contribute to.

2. **Click the "Fork" button:**
   - On the top-right corner of the repository page, click the **"Fork"** button.

   ![Fork Button](./images/fork_button.png)

   - Select (step 1 image below) your personal account (or the organization where you have rights) to create the fork and click Create fork (step 2 image below).

   ![Fork Creation](./images/creating_fork.png)

3. **Wait for the fork to be created:**
   - GitHub will take a moment to copy the repository's contents.
   - Once completed, you'll have a new repository under your GitHub account's namespace, e.g. `github.com/your-username/repository-name`.

4. **Clone your fork locally:**
   - On your fork's page, click the **"Code"** button.

   ![Clone Button](./images/clone_button.png)

   - Copy the URL (SSH or HTTPS).

   ![Copying Git Reference](./images/copying_git_reference.png)

   - Run `git clone <copied-url>` in your terminal to get a local copy of the forked repository.

**Next Step:**
Proceed to make changes in a branch and then prepare a Pull Request to merge your updates back into the original repository.
