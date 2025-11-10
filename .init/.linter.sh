#!/bin/bash
cd /home/kavia/workspace/code-generation/expense-splitter-for-small-shops-40774-40784/expense_api
source venv/bin/activate
flake8 .
LINT_EXIT_CODE=$?
if [ $LINT_EXIT_CODE -ne 0 ]; then
  exit 1
fi

