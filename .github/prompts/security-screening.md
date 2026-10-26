REPO: ${REPO}
PR NUMBER: ${PR_NUMBER}

Read the diff with `gh pr diff` and decide whether it touches security.

It does when it changes how the code handles untrusted input, such as model output and tool
results, secrets, credentials, the headers sent to vendors and tool servers, network requests,
logs, file paths, processes, permissions, dependencies or CI workflows.

Answer true when unsure.
