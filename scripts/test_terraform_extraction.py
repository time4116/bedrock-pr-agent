"""
Test script to extract Terraform plans from a GitHub Actions log using the same logic as terraform_validator.py.

Pass the path to a downloaded GHA log .txt file as input_file in main().
"""
import re
from typing import List, Dict, Any


def clean_log_text(text: str, remove_timestamps: bool = False) -> str:
    """
    Clean log text by removing ANSI color codes, excessive whitespace, and pipeline annotations.

    Args:
        text: Raw log text
        remove_timestamps: If True, also remove timestamps like [2025-12-12T20:45:39.920Z]
    """
    # Remove ANSI escape codes
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    text = ansi_escape.sub('', text)
    
    # Remove [Pipeline] lines - saves ~33% of tokens
    text = re.sub(r'^\[Pipeline\].*$', '', text, flags=re.MULTILINE)
    
    # Optionally remove timestamps - format: [2025-12-12T20:45:39.920Z]
    if remove_timestamps:
        text = re.sub(r'\[\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z\]\s*', '', text)
    
    # Remove excessive blank lines (more than 2 consecutive)
    text = re.sub(r'\n{3,}', '\n\n', text)
    
    return text


def analyze_plan_deletions(plan_text: str) -> Dict[str, Any]:
    """
    Analyze a Terraform plan for resource deletions and replacements.
    (Simplified from terraform_validator.py)
    """
    deletion_analysis = {
        'has_deletions': False,
        'deletion_count': 0,
        'deleted_resources': [],
        'has_replacements': False,
        'replacement_count': 0,
        'replaced_resources': []
    }
    
    lines = plan_text.split('\n')
    
    for line in lines:
        # Look for "will be destroyed" pattern
        if 'will be destroyed' in line.lower():
            deletion_analysis['has_deletions'] = True
            deletion_analysis['deletion_count'] += 1
            match = re.search(r'#\s+([^\s]+)\s+will be destroyed', line)
            if match:
                deletion_analysis['deleted_resources'].append(match.group(1))
        
        # Look for "must be replaced" pattern
        if 'must be replaced' in line.lower() or 'forces replacement' in line.lower():
            deletion_analysis['has_replacements'] = True
            deletion_analysis['replacement_count'] += 1
            match = re.search(r'#\s+([^\s]+)\s+', line)
            if match and match.group(1) not in deletion_analysis['replaced_resources']:
                deletion_analysis['replaced_resources'].append(match.group(1))
    
    return deletion_analysis


def extract_terraform_plans(log_content: str) -> List[Dict[str, Any]]:
    """
    Extract Terraform plan sections from Jenkins log.
    (Same logic as terraform_validator.py)
    """
    plans = []
    lines = log_content.split('\n')
    
    i = 0
    while i < len(lines):
        line = lines[i]
        
        # Look for Terraform plan marker
        if 'Terraform will perform the following actions:' in line:
            # Capture the plan section
            plan_lines = [line]
            i += 1
            
            # Capture subsequent lines until we hit the Plan summary
            while i < len(lines):
                current_line = lines[i]
                
                # Add the line first
                plan_lines.append(current_line)
                
                # Stop at plan summary line
                if 'Plan:' in current_line and ('to add' in current_line or 'to change' in current_line or 'to destroy' in current_line):
                    break
                
                # Safety: Stop at next plan section
                if i > 0 and 'Terraform will perform the following actions:' in current_line:
                    plan_lines.pop()
                    i -= 1
                    break
                
                i += 1
            
            if len(plan_lines) > 1:
                plan_text = '\n'.join(plan_lines)
                plan_size = len(plan_text)
                
                deletion_summary = analyze_plan_deletions(plan_text)
                
                plans.append({
                    'plan': plan_text,
                    'deletion_summary': deletion_summary,
                    'plan_size': plan_size
                })
            continue
        
        i += 1
    
    return plans


def main():
    input_file = "path/to/your-gha-log.txt"
    
    print("=" * 80)
    print("TERRAFORM PLAN EXTRACTION TEST")
    print("=" * 80)
    
    # Read the log file
    print(f"\n1. Reading log file: {input_file}")
    with open(input_file, 'r', encoding='utf-8', errors='ignore') as f:
        raw_log = f.read()
    
    original_size = len(raw_log)
    print(f"   Original size: {original_size:,} bytes ({original_size / 1024:.2f} KB, {original_size / (1024 * 1024):.2f} MB)")
    print(f"   Estimated tokens (raw): {original_size / 4:,.0f}")
    
    # Clean the log (remove ANSI codes, [Pipeline] lines)
    print("\n2. Cleaning log (removing ANSI codes and [Pipeline] lines)...")
    cleaned_log = clean_log_text(raw_log, remove_timestamps=False)
    cleaned_size = len(cleaned_log)
    bytes_saved_cleaning = original_size - cleaned_size
    
    print(f"   Cleaned size: {cleaned_size:,} bytes ({cleaned_size / 1024:.2f} KB, {cleaned_size / (1024 * 1024):.2f} MB)")
    print(f"   Bytes removed by cleaning: {bytes_saved_cleaning:,} ({bytes_saved_cleaning / original_size * 100:.1f}%)")
    print(f"   Estimated tokens (cleaned): {cleaned_size / 4:,.0f}")
    
    # Test timestamp removal
    print("\n2b. Testing timestamp removal...")
    cleaned_log_no_timestamps = clean_log_text(raw_log, remove_timestamps=True)
    cleaned_no_ts_size = len(cleaned_log_no_timestamps)
    bytes_saved_timestamps = cleaned_size - cleaned_no_ts_size
    
    print(f"   Cleaned + no timestamps: {cleaned_no_ts_size:,} bytes ({cleaned_no_ts_size / 1024:.2f} KB, {cleaned_no_ts_size / (1024 * 1024):.2f} MB)")
    print(f"   Bytes saved by removing timestamps: {bytes_saved_timestamps:,} ({bytes_saved_timestamps / cleaned_size * 100:.1f}%)")
    print(f"   Estimated tokens saved: {bytes_saved_timestamps / 4:,.0f}")
    
    # Use the version with timestamps removed for extraction
    cleaned_log = cleaned_log_no_timestamps
    cleaned_size = cleaned_no_ts_size
    
    # Extract Terraform plans
    print("\n3. Extracting Terraform plan sections...")
    plans = extract_terraform_plans(cleaned_log)
    
    if not plans:
        print("   ❌ No Terraform plans found in log!")
        return
    
    total_plan_size = sum(p['plan_size'] for p in plans)
    bytes_saved_extraction = cleaned_size - total_plan_size
    
    print(f"   Found {len(plans)} Terraform plan(s)")
    print(f"   Total plan size: {total_plan_size:,} bytes ({total_plan_size / 1024:.2f} KB, {total_plan_size / (1024 * 1024):.2f} MB)")
    print(f"   Bytes removed by extraction: {bytes_saved_extraction:,} ({bytes_saved_extraction / cleaned_size * 100:.1f}%)")
    print(f"   Estimated tokens (plans only): {total_plan_size / 4:,.0f}")
    
    # Show individual plan details
    print("\n4. Individual Plan Details:")
    for idx, plan_data in enumerate(plans, 1):
        plan_size = plan_data['plan_size']
        deletion_summary = plan_data['deletion_summary']
        
        print(f"\n   Plan #{idx}:")
        print(f"      Size: {plan_size:,} bytes ({plan_size / 1024:.2f} KB)")
        print(f"      Estimated tokens: {plan_size / 4:,.0f}")
        print(f"      Has deletions: {deletion_summary['has_deletions']} ({deletion_summary['deletion_count']} resources)")
        print(f"      Has replacements: {deletion_summary['has_replacements']} ({deletion_summary['replacement_count']} resources)")
        
        if deletion_summary['deleted_resources']:
            print(f"      Deleted resources: {', '.join(deletion_summary['deleted_resources'][:5])}")
            if len(deletion_summary['deleted_resources']) > 5:
                print(f"         ... and {len(deletion_summary['deleted_resources']) - 5} more")
    
    # Summary
    print("\n" + "=" * 80)
    print("SUMMARY - TOKEN SAVINGS BREAKDOWN")
    print("=" * 80)
    total_bytes_saved = original_size - total_plan_size
    print(f"Original log:              {original_size:>12,} bytes  →  {original_size / 4:>10,.0f} tokens")
    print(f"After ANSI/[Pipeline]:     {original_size - bytes_saved_cleaning:>12,} bytes  →  {(original_size - bytes_saved_cleaning) / 4:>10,.0f} tokens (saved {bytes_saved_cleaning / 4:>8,.0f})")
    print(f"After timestamp removal:   {cleaned_size:>12,} bytes  →  {cleaned_size / 4:>10,.0f} tokens (saved {bytes_saved_timestamps / 4:>8,.0f})")
    print(f"After plan extraction:     {total_plan_size:>12,} bytes  →  {total_plan_size / 4:>10,.0f} tokens (saved {bytes_saved_extraction / 4:>8,.0f})")
    print(f"\n{'─' * 80}")
    print(f"Total reduction:           {total_bytes_saved:>12,} bytes  ({total_bytes_saved / original_size * 100:.1f}%)")
    print(f"Total tokens saved:        {total_bytes_saved / 4:>10,.0f} tokens ({total_bytes_saved / original_size * 100:.1f}% reduction)")
    
    # Save extracted plans to file for inspection
    output_file = "extracted_plans.txt"
    print(f"\n5. Saving extracted plans to: {output_file}")
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write("=" * 80 + "\n")
        f.write("EXTRACTED TERRAFORM PLANS (with timestamps removed)\n")
        f.write("=" * 80 + "\n\n")
        
        for idx, plan_data in enumerate(plans, 1):
            f.write(f"\n{'=' * 80}\n")
            f.write(f"PLAN #{idx} - Size: {plan_data['plan_size']:,} bytes ({plan_data['plan_size'] / 1024:.2f} KB)\n")
            f.write(f"{'=' * 80}\n\n")
            f.write(plan_data['plan'])
            f.write("\n\n")
    
    print(f"   ✅ Saved extracted plans for inspection")
    print("\n" + "=" * 80)


if __name__ == '__main__':
    main()
