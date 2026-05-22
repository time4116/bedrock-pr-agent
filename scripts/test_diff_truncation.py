"""
Test script to analyze PR diff sizes and determine optimal truncation limit.

This helps us understand typical PR diff patterns and choose a good max size.
"""
import sys


def analyze_diff_truncation(diff_content: str):
    """
    Analyze a diff and show what different truncation strategies would preserve.
    """
    original_size = len(diff_content)
    
    print("=" * 80)
    print("PR DIFF TRUNCATION ANALYSIS")
    print("=" * 80)
    
    print(f"\nOriginal diff size: {original_size:,} bytes ({original_size / 1024:.2f} KB)")
    print(f"Estimated tokens: {original_size / 4:,.0f}")
    
    # Test different truncation limits
    truncation_options = [
        (100 * 1024, 40, 40),   # 100KB: 40KB first + 40KB last
        (150 * 1024, 60, 60),   # 150KB: 60KB first + 60KB last
        (200 * 1024, 80, 80),   # 200KB: 80KB first + 80KB last (current)
        (250 * 1024, 100, 100), # 250KB: 100KB first + 100KB last
        (300 * 1024, 120, 120), # 300KB: 120KB first + 120KB last
    ]
    
    print("\n" + "=" * 80)
    print("TRUNCATION STRATEGY COMPARISON")
    print("=" * 80)
    print(f"\n{'Max Size':<12} {'First/Last':<15} {'Final Size':<15} {'Tokens':<12} {'% Kept':<10} {'% Lost':<10}")
    print("-" * 80)
    
    for max_size, first_kb, last_kb in truncation_options:
        if original_size <= max_size:
            # No truncation needed
            final_size = original_size
            pct_kept = 100.0
            pct_lost = 0.0
            status = "✅ No truncation"
        else:
            # Would truncate
            first_chunk_size = first_kb * 1024
            last_chunk_size = last_kb * 1024
            final_size = first_chunk_size + last_chunk_size
            pct_kept = (final_size / original_size) * 100
            pct_lost = 100 - pct_kept
            status = f"⚠️  Truncate"
        
        print(f"{max_size // 1024}KB{'':<8} {first_kb}KB + {last_kb}KB{'':<5} {final_size // 1024}KB{'':<12} {final_size // 4:>8,.0f}   {pct_kept:>6.1f}%    {pct_lost:>6.1f}%  {status}")
    
    # Analyze file change distribution in diff
    print("\n" + "=" * 80)
    print("DIFF CONTENT ANALYSIS")
    print("=" * 80)
    
    # Count file headers
    file_count = diff_content.count('diff --git')
    print(f"\nFiles changed: {file_count}")
    
    # Estimate lines
    line_count = diff_content.count('\n')
    print(f"Total lines: {line_count:,}")
    
    # Addition/deletion balance
    additions = diff_content.count('\n+')
    deletions = diff_content.count('\n-')
    print(f"Lines added: {additions:,}")
    print(f"Lines deleted: {deletions:,}")
    
    print("\n" + "=" * 80)
    print("RECOMMENDATION")
    print("=" * 80)
    
    if original_size <= 150 * 1024:
        print("\n✅ This diff is small/medium sized.")
        print("   Recommendation: 200KB limit (current) is more than sufficient.")
    elif original_size <= 250 * 1024:
        print("\n⚠️  This is a large diff.")
        print("   Recommendation: Consider 250KB limit (100KB + 100KB) to preserve more context.")
    else:
        print("\n🚨 This is a VERY LARGE diff.")
        print("   Recommendation:")
        print("   - 250-300KB limit for maximum context preservation")
        print("   - OR: Ask developers to split into smaller PRs")
        print("   - Large PRs are harder to review and more error-prone")


def main():
    if len(sys.argv) != 2:
        print("Usage: python test_diff_truncation.py <path_to_diff_file>")
        print("\nTo get a PR diff:")
        print("  gh pr view <PR_NUMBER> --repo owner/repo --json diffUrl -q .diffUrl | curl -sL > pr_diff.txt")
        sys.exit(1)
    
    diff_file = sys.argv[1]
    
    try:
        with open(diff_file, 'r', encoding='utf-8', errors='ignore') as f:
            diff_content = f.read()
        
        analyze_diff_truncation(diff_content)
        
    except FileNotFoundError:
        print(f"Error: File not found: {diff_file}")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
