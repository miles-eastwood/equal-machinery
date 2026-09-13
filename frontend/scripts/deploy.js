/**
 * Cross-platform deploy script.
 *
 * Publishes the production build to GitHub Pages via gh-pages, but only when
 * the current git branch is `main`. 
 */
const { execSync } = require("child_process");

const DEPLOY_REPO = "git@github.com:miles-eastwood/equal-machinery.git";
const BUILD_DIR = "build";

function currentBranch() {
  return execSync("git rev-parse --abbrev-ref HEAD", { encoding: "utf8" }).trim();
}

function main() {
  const branch = currentBranch();

  if (branch !== "main") {
    console.error(
      `Deploys are only allowed from main branch (you are on '${branch}')`
    );
    process.exit(1);
  }

  // Inherit stdio so gh-pages output/errors surface directly.
  execSync(`npx gh-pages -d ${BUILD_DIR} -r ${DEPLOY_REPO}`, {
    stdio: "inherit",
  });
}

main();
