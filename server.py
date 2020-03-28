from flask import Flask, render_template, request
import json
from typing import Sequence
from portalocker import Lock
from collections import Counter
from json2html import *

app = Flask(__name__)


def get_images(cluster: Sequence[int]) -> Sequence[str]:
    return ["static/rgb/{:08d}.jpg".format(i) for i in cluster]


@app.route("/reset")
def reset() -> str:
    # atomic access
    with Lock("jobs.json", "w") as f:
        # open for (re)write
        clusters = json.load(open("clusters.json"))

        # everything in clusters.json with proper support is a new available job
        jobs = [
            {"status": "available", "cluster": c}
            for c in [
                c["cluster"] for c in clusters if len(c["cluster"]) == c["support"]
            ]
        ]

        # write out and truncate to new size
        json.dump(jobs, f, indent=2)
        f.truncate()

        # inform the caller
        return "Reset complete. %d jobs created" % len(jobs)


@app.route("/view")
def view() -> str:
    # atomic access
    with Lock("jobs.json", "r") as f:
        # load the jobs
        jobs = json.load(f)

        # render them
        return json2html.convert(jobs)


@app.route("/progress")
def progress() -> str:
    # atomic access
    with Lock("jobs.json", "r") as f:
        # read state
        jobs = json.load(f)

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
def reclaim() -> str:
    # atomic access
    with Lock("jobs.json", "r+") as f:
        # read state
        jobs = json.load(f)

        # start reclaiming pending jobs
        # (probably opened at some point and never processed)
        reclaimed = 0
        for job in jobs:
            if job["status"] == "pending":
                job["status"] = "available"
                reclaimed += 1

        # write over
        f.seek(0)
        json.dump(jobs, f, indent=2)
        f.truncate()

        # inform the caller
        return "Reclaimed {} tasks".format(reclaimed)


@app.route("/", methods=["GET", "POST"])
def main():
    # atomic access
    with Lock("jobs.json", "r+") as f:
        # lock status, read all jobs
        jobs = json.load(f)

        # if answer has been submitted, process it
        if request.form is not None and "answer" in request.form:
            answer = json.loads(request.form["answer"])
            jobs[answer["cluster"]]["status"] = "completed"
            jobs[answer["cluster"]]["has_object"] = answer["has_object"]

        # get indices of available jobs
        available_jobs = [
            i for i, job in enumerate(jobs) if job["status"] == "available"
        ]

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

        # go to start to rewrite
        f.seek(0)
        json.dump(jobs, f, indent=2)
        f.truncate()

        # respond
        return ret


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=12346)
