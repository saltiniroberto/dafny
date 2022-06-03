# Preparing a new Dafny release

## Making a new Github release

0. Ensure that you are in a clean and up-to-date repository, with the `master`
   branch checked out and up-to-date and no uncommitted changes.

1. Select a version number `$VER` (e.g., "3.0.0" or "3.0.0-alpha"), then run
   `Scripts/release.py $VER prepare` from the root of the repository.  The
   script will check that the repository is in a good state, create and check
   out a new release branch, update `Source/version.cs` and `RELEASE_NOTES.md`,
   prepare a release commit, and push it.

2. Kick off the deep test suite by navigating to
   <https://github.com/dafny-lang/dafny/actions/workflows/deep-tests.yml>,
   clicking the "Run workflow" dropdown, selecting the newly created branch, and
   clicking the "Run workflow" button. The automation for releasing below will
   check for a run of this workflow on the exact commit to release.  (TODO:
   Run this automatically as part of the prepare-release script.)

3. Run `Scripts/release.py $VER release` from the root of the repository.  The
   script will tag the current commit and push it. (TODO: Merge with the two
   steps above.)  A GitHub action will automatically run in reaction to the tag
   being pushed, which will build the artifacts and reference manual and then
   create a draft GitHub release. You can find and watch the progress of this
   workflow at <https://github.com/dafny-lang/dafny/actions>.

4. Once the action completes, you should find the draft release at
   <https://github.com/dafny-lang/dafny/releases>. Edit the release body to add in
   the release notes from `RELEASE_NOTES.md`.  If this is not a pre-release,
   check the box to create a new discussion based on the release.

5. Push the "Publish" button. This will trigger yet another workflow
   that will download the published artifacts and run a smoke test
   on multiple platforms. Again you can watch for this workflow at
   <https://github.com/dafny-lang/dafny/actions>.

6. Create a pull request to merge the newly created branch into `master` (the
   script will give you a link to do so).  Get it approved and merged.

7. Make a PR in the <https://github.com/dafny-lang/ide-vscode> repository to
   update the list of version supported by the plugin.

8. Announce the new release to the world!

If something goes wrong, delete the tag and release in GitHub, delete the local release branch, fix the problem, and try again.

## Updating Dafny on Homebrew

The following steps are typically performed by a community member, but feel free
to perform them if you're on macOS.

Homebrew (`brew`) is a package manager for macOS. The Dafny project
maintains a brew "formula" that allows easy installation of Dafny and
its dependencies on macOS.

These are the instructions for updating the formula, which must be done
each time a new release is issued.

These instructions are meant to be executed on a Mac, in a Terminal shell.
All the Homebrew formulas are held in a GitHub repo, so some familiarity
with git commands and concepts is helpful.

0. Install Homebrew if it is not already present on your machine.
   Running `which brew` will tell you if it is. See
   <https://docs.brew.sh/Installation> if not.

1. Update brew: `brew update`

2. Find the formula: `cd $(brew --repo)/Library/Taps/homebrew/homebrew-core/Formula`

3. Prepare the repository:

        git checkout master
        git pull origin
        git checkout -b <some new branch name>

   The branch name is needed in various places below

4. Edit the formula (e.g., `vi dafny.rb`). For a normal release change,
   all that is needed is to change the name of the archive file for the
   release and its SHA.

   a) Change the line near the top of the file that looks like

          url "https://github.com/dafny-lang/dafny/archive/v2.3.0.tar.gz"

      to hold the actual release number (this is the url for the source
      asset; you can see the actual name on the Releases page for the
      latest build).
   b) Save the file
   c) Run `brew reinstall dafny`.
   d) The command will complain that the SHA does not match. Copy the
      correct SHA, reopen the file and paste the new SHA into the `sha`
      line after the `url` line.
   e) Bump up the revision number (by one) on the succeeding line.
   f) Save the file
   g) Check that you have not introduced any syntax errors by running
      `brew reinstall dafny` again. If you totally mess up the file,
      you can do `git checkout dafny.rb`.

5. Create a pull request following the instructions here:

    <https://docs.brew.sh/How-To-Open-a-Homebrew-Pull-Request>

6. Expect comments from the reviewers. If changes are needed, do 4-6
   again. Eventually the reviewers will accept and merge the PR.

7. Then bring your Homebrew installation back to normal:

        git checkout master
        git pull origin master

8. Test the installation by running

        brew reinstall dafny

   and then execute `dafny` on a sample file to see if it has the
   correct version number. Even better is to try this step on a
   different machine than the one on which the `dafny.rb` file was edited

9. If everything works you can, at your leisure do

        git branch -d <the branch name>
