"""Fill the GitHub Metrics Summary block in README.md with live values."""
import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timezone

USER = os.environ.get("GH_USER", "rickrick3")
TOKEN = os.environ["GH_TOKEN"]
README = "README.md"
START, END = "<!-- STATS:START -->", "<!-- STATS:END -->"


def gql(query, **variables):
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": query, "variables": variables}).encode(),
        headers={"Authorization": f"bearer {TOKEN}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as resp:
        body = json.load(resp)
    if body.get("errors"):
        sys.exit(f"GraphQL error: {body['errors']}")
    return body["data"]


def search_count(q):
    query = "query($q:String!){search(query:$q,type:ISSUE){issueCount}}"
    return gql(query, q=q)["search"]["issueCount"]


# Totals and last-year activity
user = gql(
    """query($login:String!){user(login:$login){
      createdAt
      pullRequests{totalCount}
      merged: pullRequests(states:MERGED){totalCount}
      issues{totalCount}
      repositoryDiscussions{totalCount}
      repositoryDiscussionComments(onlyAnswers:true){totalCount}
      contributionsCollection{
        totalPullRequestReviewContributions
        commitContributionsByRepository(maxRepositories:100){repository{nameWithOwner}}
        issueContributionsByRepository(maxRepositories:100){repository{nameWithOwner}}
        pullRequestContributionsByRepository(maxRepositories:100){repository{nameWithOwner}}
        pullRequestReviewContributionsByRepository(maxRepositories:100){repository{nameWithOwner}}
      }
    }}""",
    login=USER,
)["user"]

# Stars across owned, non-fork repos
stars, cursor = 0, None
while True:
    repos = gql(
        """query($login:String!,$after:String){user(login:$login){
          repositories(first:100,after:$after,ownerAffiliations:OWNER,isFork:false){
            nodes{stargazerCount} pageInfo{hasNextPage endCursor}
        }}}""",
        login=USER,
        after=cursor,
    )["user"]["repositories"]
    stars += sum(n["stargazerCount"] for n in repos["nodes"])
    if not repos["pageInfo"]["hasNextPage"]:
        break
    cursor = repos["pageInfo"]["endCursor"]

# All-time commits and contributions (the API caps each query at one year)
created = datetime.fromisoformat(user["createdAt"].replace("Z", "+00:00"))
now = datetime.now(timezone.utc)
commits = contributions = 0
for year in range(created.year, now.year + 1):
    start = max(created, datetime(year, 1, 1, tzinfo=timezone.utc))
    end = min(now, datetime(year, 12, 31, 23, 59, 59, tzinfo=timezone.utc))
    cc = gql(
        """query($login:String!,$from:DateTime!,$to:DateTime!){user(login:$login){
          contributionsCollection(from:$from,to:$to){
            totalCommitContributions contributionCalendar{totalContributions}
        }}}""",
        login=USER,
        **{"from": start.isoformat(), "to": end.isoformat()},
    )["user"]["contributionsCollection"]
    commits += cc["totalCommitContributions"]
    contributions += cc["contributionCalendar"]["totalContributions"]

last_year = user["contributionsCollection"]
contributed_to = {
    item["repository"]["nameWithOwner"]
    for key, items in last_year.items()
    if key.endswith("ByRepository")
    for item in items
}

total_prs = user["pullRequests"]["totalCount"]
merged_prs = user["merged"]["totalCount"]
merged_pct = merged_prs / total_prs * 100 if total_prs else 0

lines = [
    f"- Total Stars Earned: {stars:,}",
    f"- Total Contributions: {contributions:,}",
    f"- Total Commits: {commits:,}",
    f"- Total PRs: {total_prs:,}",
    f"- Total PRs Merged: {merged_prs:,}",
    f"- Merged PRs Percentage: {merged_pct:.2f} %",
    f"- Total PRs Reviewed: {search_count(f'type:pr reviewed-by:{USER}'):,}",
    f"- Total Issues: {user['issues']['totalCount']:,}",
    f"- Total Discussions Started: {user['repositoryDiscussions']['totalCount']:,}",
    f"- Total Discussions Answered: {user['repositoryDiscussionComments']['totalCount']:,}",
    f"- PRs Commented: {search_count(f'type:pr commenter:{USER}'):,}",
    f"- PRs Reviewed (last year): {last_year['totalPullRequestReviewContributions']:,}",
    f"- Issues Commented: {search_count(f'type:issue commenter:{USER}'):,}",
    f"- Contributed to (last year): {len(contributed_to):,} repositories",
    "",
    f"<sub>Updated {now:%Y-%m-%d}</sub>",
]
block = f"{START}\n" + "\n".join(lines) + f"\n{END}"

with open(README, encoding="utf-8") as f:
    text = f.read()
pattern = re.escape(START) + ".*?" + re.escape(END)
if not re.search(pattern, text, flags=re.S):
    sys.exit("Stats markers not found in README.md")
with open(README, "w", encoding="utf-8") as f:
    f.write(re.sub(pattern, lambda _: block, text, flags=re.S))
