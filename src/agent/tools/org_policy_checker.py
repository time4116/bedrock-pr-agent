"""
Organization policy checker tool for Strands Agent.

Validates PR changes against policy documents stored in the policies/ directory.
Provides early feedback before merging to catch policy violations and compliance gaps.

See policies/IMPLEMENTATION.md to upgrade the underlying retrieval to vector search.
"""
import os
import re
from typing import Dict, Any, List

from src.utils.logger import logger
from src.utils import policy_store


def check_organization_policy(
    pr_diff: str,
    pr_metadata: Dict[str, str],
    changed_files: List[str]
) -> Dict[str, Any]:
    """
    Validate PR changes against organization policies.

    Queries the policy store for relevant policies based on the files being modified,
    PR context, and change patterns. Returns policy compliance results with violations,
    warnings, and recommendations. Runs BEFORE code analysis to surface issues early.

    Args:
        pr_diff: The unified diff of PR changes
        pr_metadata: Dictionary with PR context:
            - title: PR title
            - description: PR description
            - branch_name: Feature branch name
            - repo_name: Repository full name (owner/repo)
        changed_files: List of file paths being modified

    Returns:
        Dictionary with policy check results:
        {
            "success": bool,
            "policy_enabled": bool,
            "relevant_policies": List[str],
            "error": str (if failed)
        }
    """
    try:
        policy_enabled = os.environ.get('ORG_POLICY_CHECK_ENABLED', 'false').lower() == 'true'

        if not policy_enabled:
            logger.info('Organization policy check disabled')
            return {
                'success': True,
                'policy_enabled': False,
                'message': 'Organization policy checking is disabled'
            }

        logger.info('Checking organization policies', {
            'repo': pr_metadata.get('repo_name'),
            'changed_files_count': len(changed_files)
        })

        queries = _build_policy_queries(changed_files, pr_metadata, pr_diff)

        relevant_policies: List[str] = []
        for query_text in queries:
            results = policy_store.query(query_text)
            relevant_policies.extend(results)

        # Deduplicate while preserving order
        seen: set = set()
        unique_policies = []
        for p in relevant_policies:
            if p not in seen:
                seen.add(p)
                unique_policies.append(p)
        relevant_policies = unique_policies

        if not relevant_policies:
            logger.warning('No policy documents found in policies/ directory')
            return {
                'success': True,
                'policy_enabled': True,
                'violations': [],
                'warnings': [],
                'recommendations': [],
                'relevant_policies': [],
                'message': 'No policy documents found. Add .md files to the policies/ directory.'
            }

        logger.info('Loaded policies for review', {
            'policy_count': len(relevant_policies)
        })

        return {
            'success': True,
            'policy_enabled': True,
            'relevant_policies': relevant_policies,
            'queries_used': queries,
            'template_guidance': """Format organization policy check results:

### 🏛️ Organization Policy Check

**Policy Compliance**: (✅ Compliant / ⚠️ Warnings Found / 🚨 Violations Detected)

Analyze the PR diff against the retrieved organization policies and categorize findings:

**🚨 Violations (Blocking Issues):**
- Issues that MUST be fixed before merge
- Security vulnerabilities, critical compliance failures
- Examples: hardcoded credentials, missing required encryption, prohibited resource types

**⚠️ Warnings (Review Needed):**
- Issues that should be reviewed but may have valid exceptions
- Missing best practices, incomplete documentation

**ℹ️ Recommendations (Best Practices):**
- Suggestions for improvement
- Policy guidance for future work

For each finding include: clear description, specific line numbers or resources,
and suggested remediation steps.

If NO issues found: ✅ "No policy violations detected. Changes align with organization standards."
"""
        }

    except Exception as error:
        logger.error('Failed to check organization policies', {
            'error': str(error)
        })
        return {
            'success': False,
            'policy_enabled': True,
            'error': str(error),
            'message': 'Policy check failed but PR analysis will continue'
        }


def _build_policy_queries(
    changed_files: List[str],
    pr_metadata: Dict[str, str],
    pr_diff: str
) -> List[str]:
    """
    Build context-aware queries for policy lookup based on PR changes.
    """
    queries = []

    file_extensions = {os.path.splitext(f)[1] for f in changed_files}

    if '.tf' in file_extensions or '.tfvars' in file_extensions:
        queries.append('Terraform infrastructure policies and best practices')
        queries.append('Required tags and naming conventions for AWS resources')
        queries.append('Security requirements for Terraform deployments')

        aws_resources = re.findall(r'aws_([a-z0-9_]+)', pr_diff.lower())
        if aws_resources:
            services = {r.split('_')[0] for r in aws_resources}
            services_str = ', '.join(sorted(services)[:10])
            queries.append(f'AWS resource security and compliance policies for: {services_str}')

    if any(f.endswith(('.yml', '.yaml', '.json', '.config')) for f in changed_files):
        queries.append('Configuration management and security policies')

    if any('docker' in f.lower() or f.endswith('.dockerfile') for f in changed_files):
        queries.append('Container security and image scanning policies')

    if any('.github' in f or '.gitlab' in f for f in changed_files):
        queries.append('CI/CD pipeline security requirements')

    if any('secret' in f.lower() or 'credential' in f.lower() or 'key' in f.lower()
           for f in changed_files):
        queries.append('Secrets management and credential handling policies')

    if 'security_group' in pr_diff.lower() or 'network' in pr_diff.lower():
        queries.append('Network security and firewall policies')

    data_keywords = {
        'pii': 'Personally Identifiable Information (PII) handling policies',
        'pci': 'Payment Card Industry (PCI-DSS) compliance requirements',
        'gdpr': 'GDPR compliance and data privacy requirements',
        'password': 'Password and credential storage security policies',
        'api_key': 'API key and token management security policies',
    }
    pr_diff_lower = pr_diff.lower()
    for keyword, policy_query in data_keywords.items():
        if keyword in pr_diff_lower:
            queries.append(policy_query)

    pr_title = pr_metadata.get('title', '')
    queries.append(f'Organization policies relevant to: {pr_title}')

    unique_queries = list(dict.fromkeys(queries))
    return unique_queries[:5]
