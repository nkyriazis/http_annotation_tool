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
    with Lock("jobs.json", "w") as f:
        clusters = json.load(open("clusters.json"))
        jobs = [
            {"status": "available", "cluster": c}
            for c in [
                c["cluster"] for c in clusters if len(c["cluster"]) == c["support"]
            ]
        ]
        json.dump(jobs, f, indent=2)
        f.truncate()
        return "Reset complete. %d jobs created" % len(jobs)


@app.route("/view")
def view() -> str:
    with Lock("jobs.json", "r") as f:
        jobs = json.load(f)
        return json2html.convert(jobs)


@app.route("/progress")
def progress() -> str:
    with Lock("jobs.json", "r") as f:
        jobs = json.load(f)
        counter = Counter([x["status"] for x in jobs])
        return render_template(
            "progress.html",
            total=len(jobs),
            available=counter.get("available", 0),
            pending=counter.get("pending", 0),
            completed=counter.get("completed", 0),
        )


@app.route("/reclaim")
def reclaim() -> str:
    with Lock("jobs.json", "r+") as f:
        jobs = json.load(f)
        reclaimed = 0
        for job in jobs:
            if job["status"] == "pending":
                job["status"] = "available"
                reclaimed += 1

        f.seek(0)
        json.dump(jobs, f, indent=2)
        f.truncate()

        return "Reclaimed {} tasks".format(reclaimed)


@app.route("/", methods=["GET", "POST"])
def main():
    with Lock("jobs.json", "r+") as f:
        # lock status, read all jobs
        jobs = json.load(f)

        # if answer has been submitted, process it
        if request.form is not None and "answer" in request.form:
            answer = json.loads(request.form["answer"])
            jobs[answer["cluster"]]["status"] = "completed"
            jobs[answer["cluster"]]["has_object"] = answer["has_object"]

        # find the next available job and dispatch
        available_jobs = [
            i for i, job in enumerate(jobs) if job["status"] == "available"
        ]

        completed_jobs = [
            i for i, job in enumerate(jobs) if job["status"] == "completed"
        ]

        ret = "Nothing to do!"
        if len(available_jobs):
            next_id = available_jobs[0]
            job = jobs[next_id]

            job["status"] = "pending"
            images = get_images(job["cluster"])
            ret = render_template(
                "index.html",
                cluster_size=len(images),
                cluster_images=get_images(job["cluster"]),
                cluster_index=next_id,
                annotated=len(completed_jobs),
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
