from playwright.sync_api import sync_playwright
import csv
import time
import re

SEARCH_QUERY = "language:Python stars:>100 pushed:>2024-01-01"
MAX_REPOS = 5
MAX_FILES_PER_REPO = 5


def extract_comments_from_code(code_text):
    """Extract Python comments from code text."""
    comments = []
    lines = code_text.split('\n')
    in_docstring = False
    docstring_char = None
    
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        
        # Skip empty lines
        if not stripped:
            continue
        
        # Handle single-line comments
        if stripped.startswith('#'):
            comments.append((i, line.rstrip()))
            continue
        
        # Handle docstrings
        if '"""' in line or "'''" in line:
            if '"""' in line:
                char = '"""'
            else:
                char = "'''"
            
            # Count occurrences
            count = line.count(char)
            
            if not in_docstring:
                # Starting a docstring
                in_docstring = True
                docstring_char = char
                comments.append((i, line.rstrip()))
                
                # Check if it's a single-line docstring
                if count == 2:
                    in_docstring = False
            else:
                # Ending a docstring
                comments.append((i, line.rstrip()))
                if char == docstring_char:
                    in_docstring = False
        elif in_docstring:
            # Inside a multi-line docstring
            comments.append((i, line.rstrip()))
    
    return comments


def find_python_files_in_repo(page, repo_url, repo_name):
    """
    Find Python files in a repository by exploring directories.
    Returns a dict of {file_url: file_name}
    """
    file_urls = {}
    visited_urls = set()
    
    print(f"\n  {'='*60}")
    print(f"  DETAILED FILE SEARCH FOR: {repo_name}")
    print(f"  {'='*60}")
    
    def explore_directory(dir_url, depth=0):
        if len(file_urls) >= MAX_FILES_PER_REPO:
            print(f"  {'  '*depth}✓ Reached MAX_FILES_PER_REPO ({MAX_FILES_PER_REPO}), stopping search")
            return
            
        if depth > 3:  # Increased from 2 to 3
            print(f"  {'  '*depth}⚠️  Max depth reached, stopping")
            return
        
        if dir_url in visited_urls:
            print(f"  {'  '*depth}⤷ Already visited, skipping")
            return
        visited_urls.add(dir_url)
        
        try:
            path_display = dir_url.split('/tree/')[-1] if '/tree/' in dir_url else 'root'
            print(f"  {'  '*depth}📁 Exploring: {path_display}")
            page.goto(dir_url)
            time.sleep(2)
            
            # Find all file and directory entries
            entries = page.locator("a[href]").all()
            print(f"  {'  '*depth}   Found {len(entries)} total links on page")
            
            directories = []
            files_found_here = 0
            dirs_found_here = 0
            
            for entry in entries:
                try:
                    href = entry.get_attribute("href")
                    if not href:
                        continue
                    
                    # Must be a GitHub URL with proper path
                    if not ('github.com' in href or href.startswith('/')):
                        continue
                    
                    # Python file found
                    if '/blob/' in href and '.py' in href:
                        file_name = href.split('/')[-1]
                        if file_name.endswith('.py'):
                            file_url = f"https://github.com{href}" if href.startswith('/') else href
                            if file_url not in file_urls:
                                file_urls[file_url] = file_name
                                files_found_here += 1
                                print(f"  {'  '*depth}   ✓ Found Python file #{len(file_urls)}: {file_name}")
                                
                                if len(file_urls) >= MAX_FILES_PER_REPO:
                                    print(f"  {'  '*depth}   🎯 Reached target of {MAX_FILES_PER_REPO} files!")
                                    return
                    
                    # Directory found
                    elif '/tree/' in href and depth < 3:  # Increased depth
                        path_parts = href.split('/tree/')
                        if len(path_parts) > 1:
                            dir_path = path_parts[-1]
                            dir_name = dir_path.split('/')[-1].lower()
                            
                            # Reduced skip list - only skip obvious non-source dirs
                            skip_dirs = ['node_modules', '.git', '__pycache__', 'venv', 'env', 
                                       'dist', 'build', '.github', '.vscode', '.idea']
                            if not any(skip in dir_name for skip in skip_dirs):
                                full_dir_url = f"https://github.com{href}" if href.startswith('/') else href
                                if '?' in full_dir_url:
                                    full_dir_url = full_dir_url.split('?')[0]
                                if '#' in full_dir_url:
                                    full_dir_url = full_dir_url.split('#')[0]
                                
                                if full_dir_url not in directories:
                                    directories.append(full_dir_url)
                                    dirs_found_here += 1
                except:
                    continue
            
            print(f"  {'  '*depth}   Summary: {files_found_here} .py files, {dirs_found_here} subdirs")
            
            # Explore subdirectories
            if directories and len(file_urls) < MAX_FILES_PER_REPO:
                print(f"  {'  '*depth}   Will explore {min(len(directories), 10)} subdirectories...")
                for dir_url_sub in directories[:10]:  # Increased from 5 to 10
                    if len(file_urls) >= MAX_FILES_PER_REPO:
                        break
                    explore_directory(dir_url_sub, depth + 1)
        
        except Exception as e:
            print(f"  {'  '*depth}   ❌ Error: {e}")
    
    # Start exploration from the repository root
    explore_directory(repo_url)
    
    print(f"  {'='*60}")
    print(f"  SEARCH COMPLETE: Found {len(file_urls)} Python files")
    if len(file_urls) < MAX_FILES_PER_REPO:
        print(f"  ⚠️  WARNING: Only found {len(file_urls)}/{MAX_FILES_PER_REPO} files!")
    print(f"  {'='*60}\n")
    
    return file_urls


def main():
    repos = []
    all_comments = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(viewport={"width": 1400, "height": 900})
        page = context.new_page()

        # -------------------------------------------------
        # 1. Search GitHub - Direct URL approach
        # -------------------------------------------------
        print("Searching GitHub repositories...")
        import urllib.parse
        encoded_query = urllib.parse.quote(SEARCH_QUERY)
        search_url = f"https://github.com/search?q={encoded_query}&type=repositories"
        
        print(f"Going to: {search_url}")
        page.goto(search_url)
        
        print("Waiting for search results...")
        time.sleep(5)
        
        # Wait for results with multiple attempts
        results_loaded = False
        try:
            page.wait_for_selector("div[data-testid='results-list']", timeout=10000)
            results_loaded = True
            print("Results loaded (modern UI)")
        except:
            try:
                page.wait_for_selector("ul.repo-list", timeout=5000)
                results_loaded = True
                print("Results loaded (classic UI)")
            except:
                print("Warning: Could not detect results container, trying anyway...")
        
        time.sleep(2)

        # Extract repository information
        print("Extracting repository information...")
        repo_links = []
        
        # Strategy 1: Modern UI with data-testid
        try:
            result_items = page.locator("div[data-testid='results-list'] > div").all()
            print(f"Found {len(result_items)} result items")
            
            for item in result_items:
                try:
                    repo_link = item.locator("a[href*='/'][href*='/']").first
                    href = repo_link.get_attribute("href")
                    text = repo_link.inner_text().strip()
                    
                    if href and '/' in text and text.count('/') == 1:
                        full_url = f"https://github.com{href}" if href.startswith('/') else href
                        if '/tree/' in full_url or '/blob/' in full_url:
                            full_url = '/'.join(full_url.split('/')[:5])
                        
                        repo_links.append((text, full_url))
                        print(f"  Found: {text}")
                        
                        if len(repo_links) >= MAX_REPOS:
                            break
                except Exception as e:
                    continue
        except Exception as e:
            print(f"Strategy 1 failed: {e}")
        
        # Strategy 2: Look for specific repo link patterns
        if len(repo_links) < MAX_REPOS:
            try:
                all_links = page.locator("a[href]").all()
                for link in all_links:
                    try:
                        href = link.get_attribute("href")
                        if href and href.startswith('/') and href.count('/') == 2:
                            parts = href.strip('/').split('/')
                            if len(parts) == 2 and not any(x in href for x in ['search', 'topics', 'marketplace', 'pricing']):
                                repo_name = f"{parts[0]}/{parts[1]}"
                                full_url = f"https://github.com{href}"
                                
                                if not any(r[0] == repo_name for r in repo_links):
                                    repo_links.append((repo_name, full_url))
                                    print(f"  Found: {repo_name}")
                                    
                                    if len(repo_links) >= MAX_REPOS:
                                        break
                    except:
                        continue
            except Exception as e:
                print(f"Strategy 2 failed: {e}")

        print(f"\nTotal repositories found: {len(repo_links)}")

        if not repo_links:
            print("ERROR: No repositories found! Check if GitHub search is working.")
            browser.close()
            return

        # Extract stars and last updated date for each repo
        for repo_name, repo_url in repo_links[:MAX_REPOS]:
            try:
                print(f"\nVisiting: {repo_name}")
                page.goto(repo_url)
                time.sleep(2)
                
                stars = "N/A"
                updated = "N/A"
                
                try:
                    star_elem = page.locator("#repo-stars-counter-star").first
                    if star_elem.count() > 0:
                        stars = star_elem.get_attribute("title") or star_elem.inner_text().strip()
                except:
                    try:
                        star_elem = page.locator("a[href$='/stargazers']").first
                        stars = star_elem.inner_text().strip()
                    except:
                        pass
                
                try:
                    time_elem = page.locator("relative-time").first
                    if time_elem.count() > 0:
                        updated = time_elem.get_attribute("datetime")
                        if not updated:
                            updated = time_elem.inner_text().strip()
                    
                    if updated == "N/A" or not updated:
                        commit_time = page.locator("relative-time[datetime]").first
                        if commit_time.count() > 0:
                            updated = commit_time.get_attribute("datetime") or commit_time.inner_text().strip()
                except Exception as e:
                    print(f"  Could not find updated date: {e}")
                
                repos.append((repo_name, stars, updated, repo_url))
                print(f"  Stars: {stars}")
                print(f"  Updated: {updated}")
                
            except Exception as e:
                print(f"  Error getting repo details: {e}")
                repos.append((repo_name, "N/A", "N/A", repo_url))

        # Save repos.csv
        with open("repos.csv", "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["repo", "stars", "updated", "url"])
            writer.writerows(repos)

        print(f"\n{'='*50}")
        print(f"Saved repos.csv with {len(repos)} repositories")
        print(f"{'='*50}\n")

        # -------------------------------------------------
        # 2. Visit each repo & extract comments
        # -------------------------------------------------
        file_processing_summary = {}
        
        for repo_name, _, _, repo_url in repos:
            print(f"\n{'#'*70}")
            print(f"PROCESSING REPO: {repo_name}")
            print(f"{'#'*70}")
            
            file_processing_summary[repo_name] = {
                'files_found': 0,
                'files_processed': 0,
                'files_with_comments': 0,
                'files_without_comments': 0,
                'total_comments': 0
            }
            
            try:
                # Find Python files
                print(f"Searching for Python files in {repo_name}...")
                file_urls = find_python_files_in_repo(page, repo_url, repo_name)
                
                file_processing_summary[repo_name]['files_found'] = len(file_urls)

                if not file_urls:
                    print(f"❌ No Python files found in {repo_name}\n")
                    continue

                print(f"✓ Found {len(file_urls)} Python files")
                print(f"Will process up to {min(len(file_urls), MAX_FILES_PER_REPO)} files\n")

                # Process each Python file
                file_num = 0
                for file_url, file_name in list(file_urls.items())[:MAX_FILES_PER_REPO]:
                    file_num += 1
                    try:
                        print(f"  [{file_num}/{min(len(file_urls), MAX_FILES_PER_REPO)}] Processing: {file_name}")
                        
                        # Get raw URL
                        raw_url = file_url.replace('/blob/', '/raw/')
                        
                        page.goto(raw_url)
                        time.sleep(1)
                        
                        # Get code content
                        code_text = page.locator("body").inner_text()
                        
                        if code_text and len(code_text) > 10:
                            # Extract comments
                            comments = extract_comments_from_code(code_text)
                            
                            file_processing_summary[repo_name]['files_processed'] += 1
                            
                            if len(comments) > 0:
                                for line_no, comment in comments:
                                    all_comments.append((repo_name, file_name, line_no, comment))
                                
                                file_processing_summary[repo_name]['files_with_comments'] += 1
                                file_processing_summary[repo_name]['total_comments'] += len(comments)
                                print(f"      ✓ Extracted {len(comments)} comments")
                            else:
                                file_processing_summary[repo_name]['files_without_comments'] += 1
                                print(f"      ⚠️  NO COMMENTS found in this file")
                        else:
                            print(f"      ❌ No code content retrieved")
                        
                    except Exception as e:
                        print(f"      ❌ Error: {e}")
                        continue

                print(f"\n  Summary for {repo_name}:")
                print(f"    Files found: {file_processing_summary[repo_name]['files_found']}")
                print(f"    Files processed: {file_processing_summary[repo_name]['files_processed']}")
                print(f"    Files with comments: {file_processing_summary[repo_name]['files_with_comments']}")
                print(f"    Files without comments: {file_processing_summary[repo_name]['files_without_comments']}")
                print(f"    Total comments: {file_processing_summary[repo_name]['total_comments']}")

            except Exception as e:
                print(f"❌ Error processing repo: {e}\n")
                continue

        # -------------------------------------------------
        # 3. Save comments.csv
        # -------------------------------------------------
        with open("comments.csv", "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["repo", "file", "line", "comment"])
            writer.writerows(all_comments)

        print(f"\n{'='*70}")
        print(f"FINAL SUMMARY")
        print(f"{'='*70}")
        print(f"Total repositories: {len(repos)}")
        print(f"Total comments collected: {len(all_comments)}")
        print(f"\nPer-Repo Breakdown:")
        for repo_name, summary in file_processing_summary.items():
            print(f"\n  {repo_name}:")
            print(f"    Files found: {summary['files_found']}")
            print(f"    Files processed: {summary['files_processed']}")
            print(f"    Files with comments: {summary['files_with_comments']}")
            print(f"    Files without comments: {summary['files_without_comments']}")
            print(f"    Total comments: {summary['total_comments']}")
            
            if summary['files_found'] < MAX_FILES_PER_REPO:
                print(f"    ⚠️  WARNING: Only found {summary['files_found']}/{MAX_FILES_PER_REPO} files!")
            if summary['files_without_comments'] > 0:
                print(f"    ℹ️  Note: {summary['files_without_comments']} files had no comments")
        
        print(f"\n{'='*70}")
        print(f"Files saved:")
        print(f"  ✓ repos.csv ({len(repos)} repositories)")
        print(f"  ✓ comments.csv ({len(all_comments)} comments)")
        print(f"{'='*70}\n")
        
        browser.close()


if __name__ == "__main__":
    main()