from flask import Flask, render_template, request
import json
from typing import Sequence, Callable, Mapping, Union
from portalocker import Lock
from collections import Counter
from json2html import *  # noqa F703
from functools import wraps
import git

app = Flask(__name__)

# A schema for the kind of jobs we're deaing with
Jobs = Sequence[Mapping[str, Union[Sequence[int], str, int]]]


def get_images(cluster: Sequence[int]) -> Sequence[str]:
    return ["static/rgb/{:08d}.jpg".format(i) for i in cluster]


def jobs_access(reads: bool = True, writes: bool = False):
    def reads_or_writes_jobs(fn: Callable) -> Callable:
        """
        Jobs are loaded and passed into the delegate as a python object.
        Upon return, the update is mirrored on disk.
        This is an atomic operation on jobs.
        """

        @wraps(fn)
        def function(*args, **kwargs):
            # atomic operation
            with Lock("backup/jobs.json", "w" if writes and not reads else "r+") as f:
                if reads:
                    # read, or create an empty one
                    try:
                        jobs = json.load(f)
                    except:  # noqa F841
                        jobs = []
                else:
                    jobs = []

                # pass the jobs and an arg and delegate
                kwargs.update({"jobs": jobs})
                ret = fn(*args, **kwargs)

                # check whether to write
                if writes:
                    # write out and truncate to new size
                    f.seek(0)
                    json.dump(jobs, f, indent=2)
                    f.truncate()

                    # update git, for backup
                    repo = git.Repo("backup")
                    repo.index.add("jobs.json")
                    repo.index.commit(
                        "Changed due to '{}' from {}".format(
                            fn.__name__, request.remote_addr
                        )
                    )

                # propagate back result
                return ret

        return function

    return reads_or_writes_jobs


@app.route("/reset")
@jobs_access(reads=False, writes=True)
def reset(jobs: Jobs) -> str:
    clusters = json.load(open("clusters.json"))

    jobs.clear()
    for cluster in clusters:
        if len(cluster["cluster"]) == cluster["support"]:
            jobs.append({"status": "available", "cluster": cluster["cluster"]})

    # inform the caller
    return "Reset complete. %d jobs created" % len(jobs)


@app.route("/view")
@jobs_access(reads=True, writes=False)
def view(jobs: Jobs) -> str:
    # render them
    return json2html.convert(jobs)


@app.route("/progress")
@jobs_access(reads=True, writes=False)
def progress(jobs: Jobs) -> str:
    # count statuses
    counter = Counter([x["status"] for x in jobs])

    # render progress
    return render_template(
        "progress.html",
        total=len(jobs),
        available=counter.get("available", 0),
        pending=counter.get("pending", 0),
        completed=counter.get("completed", 0),
    )


@app.route("/reclaim")
@jobs_access(reads=True, writes=True)
def reclaim(jobs: Jobs) -> str:
    # start reclaiming pending jobs
    # (probably opened at some point and never processed)
    reclaimed = 0
    for job in jobs:
        if job["status"] == "pending":
            job["status"] = "available"
            reclaimed += 1

    # inform the caller
    return "Reclaimed {} tasks".format(reclaimed)


@app.route("/", methods=["GET", "POST"])
@jobs_access(reads=True, writes=True)
def main(jobs: Jobs):
    # if answer has been submitted, process it
    if request.form is not None and "answer" in request.form:
        answer = json.loads(request.form["answer"])
        jobs[answer["cluster"]]["status"] = "completed"
        jobs[answer["cluster"]]["has_object"] = answer["has_object"]

    # get indices of available jobs
    available_jobs = [i for i, job in enumerate(jobs) if job["status"] == "available"]

    # count completed jobs
    completed_jobs = len([job for job in jobs if job["status"] == "completed"])

    ret = "Nothing to do!"
    if len(available_jobs):
        # fetch next job
        next_id = available_jobs[0]
        job = jobs[next_id]

        # remove the job from the "queue"
        job["status"] = "pending"

        # get the image urls
        images = get_images(job["cluster"])

        # render UI
        ret = render_template(
            "index.html",
            cluster_size=len(images),
            cluster_images=get_images(job["cluster"]),
            cluster_index=next_id,
            annotated=completed_jobs,
            total=len(jobs),
        )

    # respond
    return ret


if __name__ == "__main__":
    # make sure there is a backup git repo, under backup
    try:
        git.Repo("backup")
    except:
        git.Repo.init("backup")
        git.Repo("backup")

    app.run(debug=True, host="0.0.0.0", port=12346)
