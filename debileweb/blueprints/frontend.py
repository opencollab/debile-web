# Copyright (c) 2012 Paul Tagliamonte <paultag@debian.org>
# Copyright (c) 2013 Leo Cavaille <leo@cavaille.net>
# Copyright (c) 2013 Sylvestre Ledru <sylvestre@debian.org>
#
# Permission is hereby granted, free of charge, to any person obtaining a
# copy of this software and associated documentation files (the "Software"),
# to deal in the Software without restriction, including without limitation
# the rights to use, copy, modify, merge, publish, distribute, sublicense,
# and/or sell copies of the Software, and to permit persons to whom the
# Software is furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.  IN NO EVENT SHALL
# THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
# FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
# DEALINGS IN THE SOFTWARE.

from flask import Blueprint, render_template, send_file, request, redirect
from flask.ext.jsonpify import jsonify

from sqlalchemy import func
from sqlalchemy.orm import joinedload
from sqlalchemy.sql.expression import bindparam


from debilemaster.orm import Source, Binary, Machine, User, Job, Group
from debilemaster.config import Config
from debilemaster.server import Session
from debilemaster.archive import UserRepository

from humanize import naturaltime
from humanize.time import naturaldelta

from datetime import timedelta
import datetime as dt
import os.path
import re
from forms import SearchPackageForm
from consts import PREFIXES_DEFAULT

frontend = Blueprint('frontend', __name__, template_folder='templates')


@frontend.app_template_filter('ago')
def ago_display(when):
    if when is None:
        return "never"
    td = dt.datetime.utcnow() - when
    return naturaltime(td)


def get_packages_prefixes():
    """
    returns the packages prefixes (a, b, ..., liba, libb, ..., y, z)
    Note that this could be computed from the database ... but since we
    are rebuilding Debian, we will have all letters + lib*
    """
    return PREFIXES_DEFAULT

def get_package_link(p):
    if p.type == "source":
        return "/source/%s/%s/%s/%s" % (p.user.login, p.name, p.version, p.run)
    else:
        return "/notimplementedyet"


def get_machine_link(m):
    return "/machine/%s" % m.name


@frontend.route("/")
def index():
    session = Session()
    active_jobs = session.query(Job)\
        .options(joinedload('machine'))\
        .filter(Job.machine != None)\
        .filter(Job.finished_at == None)\
        .all()
    machines = session.query(Machine).options(joinedload('jobs')).all()
    active_jobs_info = []
    for j in active_jobs:
        info = {}
        info['job'] = j
        info['package_link'] = get_package_link(j.package)
        if j.machine:
            info['machine_link'] = get_machine_link(j.machine)
        active_jobs_info.append(info)

    pending_jobs = session.query(Job)\
        .filter(Job.assigned_at == None)\
        .count()

    form = SearchPackageForm()
    packages_prefixes = get_packages_prefixes()

    return render_template('index.html', **{
        "active_jobs_info": active_jobs_info,
        "pending_jobs": pending_jobs,
	"packages_prefixes": packages_prefixes,
        "form": form
    })

@frontend.route("/sources/")
def source_list():
    session = Session()
    count = 100
    sources = session.query(Source)\
        .options(joinedload(Source.user))\
        .options(joinedload(Source.group))\
        .order_by(Source.created_at.desc())\
        .limit(count)
    sources_info = []
    for s in sources:
        info = {}
        info['source'] = s
        info['source_link'] = "/source/%s/%s/%s/%s" % (s.user.login, s.name, s.version, s.run)
        info['group_link'] = "/group/%s" % s.group.name
        info['user_link'] = "/worker/%s" % s.user.login
        info['user_repository_link'] = "/repository/%s" % s.user.login
        sources_info.append(info)

    return render_template('source_list.html', **{
        "sources_info": sources_info,
        "count": count,
    })



@frontend.route("/maintainer/<nameItem>/", methods=['POST','GET'])
@frontend.route("/prefix/<nameItem>/")
def list_packages(nameItem=0):
    if request.method == 'POST':
        # Switch a better url
        return redirect('/maintainer/' + re.search(r".*<(.*)>",request.form['maintainer']).group(1) + '/')

    session = Session()
    if request.path.startswith("/maintainer/"):
        # Maintainer
        sources = session.query(Source)\
            .filter(Source.maintainer.contains(nameItem))\
            .distinct(Source.name)\
            .order_by(Source.name.desc(), Source.version.desc())
    else:
        sources = session.query(Source)\
            .filter(Source.name.startswith(nameItem))\
            .distinct(Source.name)\
            .order_by(Source.name.desc(), Source.version.desc())

    sources_info = []
    for s in sources:
        info = {}
        info['source'] = s
        info['source_link'] = "/source/%s/%s/%s/%s" % (s.user.login, s.name, "latest", s.run)
        sources_info.append(info)

    return render_template('prefix.html', **{
        "sources": sources_info,
        "prefix": nameItem,
    })

@frontend.route("/group/<group_id>/")
@frontend.route("/group/<group_id>/<page>/")
def group_list(group_id, page=0):
    page = int(page)
    # FIXME : unsafe code, catch exceptions
    session = Session()
    g = session.query(Group).filter(Group.name == group_id).one()
    sources = session.query(Source).filter(Source.group == g).order_by(Source.created_at.asc()).paginate(page, per_page=15)

    return render_template('group.html', **{
        "sources": sources,
        "group_id": group_id,
        "page": page,
    })


@frontend.route("/source/search/", methods=['POST'])
@frontend.route("/source/<owner_name>/<package_name>/<package_version>/<int:run_number>")
def source(package_name="", owner_name="fred", package_version="latest", run_number=1):
    if request.method == 'POST':
        # Switch a better url
        return redirect('/source/' + owner_name + '/' + request.form['package'] + '/' + package_version + '/' + str(run_number))

    session = Session()

    # Let's compute all the versions that exists for this package
    versions_query = session.query(Source.version)\
        .join(Source.user)\
        .filter(Source.name == package_name)\
        .filter(User.login == owner_name)
    versions = sorted(set([e[0] for e in versions_query.all()]))

    if len(versions) == 0:
        return render_template('source-not-found.html', **{
                "package_name": package_name
                })

    latest_version = versions[-1]
    if package_version == 'latest':
        this_version = latest_version
    else:
        this_version = package_version

    # All runs that exist for this version
    runs_query = session.query(Source.run)\
        .join(Source.user)\
        .filter(Source.name == package_name)\
        .filter(User.login == owner_name)\
        .filter(Source.version == this_version)\
        .order_by(Source.run.asc())
    runs = [e[0] for e in runs_query.all()]

    if len(runs) == 0:
        return render_template('source-not-found.html', **{
                "package_name": package_name,
                "version": this_version
                })

    
    latest_run = runs[-1]
    if run_number == '0':
        this_run = latest_run
    else:
        this_run = run_number

    # Join load the user to show details about the source owner
    package_query = session.query(Source)\
        .options(joinedload('user'))\
        .options(joinedload('jobs'))\
        .options(joinedload('binaries'))\
        .filter(Source.name == package_name)\
        .filter(User.login == owner_name)\
        .filter(Source.version == this_version)\
        .filter(Source.run == this_run)

    try:
        package = package_query.one()
    except:
        raise Exception("This resource does not exist")

    # Compute description section
    desc = {}
    desc['user_link'] = "/worker/%s" % package.user.login
    desc['user_repository_link'] = "/repository/%s" % package.user.login

    desc['run'] = run_number
    # desc['pool_link'] =

    # Fill in the run sections if need be
    # Remember that multiple runs cannot exist with fred auto-build
    if len(runs) > 1:
        multiple_runs = True
    else:
        multiple_runs = False
    runs_info = []
    if multiple_runs:
        for r in runs:
            href = "/source/%s/%s/%s/%s" % (owner_name,
                                            package_name,
                                            package_version,
                                            r
                                            )
            runs_info.append((r, href))

    # Fill in the version sections
    if len(versions) > 1:
        multiple_versions = True
    else:
        multiple_versions = False
    versions_info = []
    if multiple_versions:
        for v in versions:
            href = "/source/%s/%s/%s/%s" % (owner_name, package_name, v, 1)
            versions_info.append((v, href))

    # Compute infos to display the job parts
    # Iterate through all jobs
    # Job total counters + compute some links
    source_jobs = session.query(Job)\
        .options(joinedload('machine'))\
        .filter(Job.package == package)\
        .order_by(Job.type, Job.subtype)\
        .all()

    total = len(source_jobs)
    unfinished = 0
    source_jobs_info = []
    for j in source_jobs:
        info = {}
        info['job'] = j
        info['job_link'] = '/report/%s/%s/%s/%s#full_log' % (package_name, this_version, j.type, j.id)
        if j.type == "clanganalyzer":
            # Special case (I know) for clang to point directly to the HTML report
            # TODO: update the path to a nicer one (like job_link)
            info['job_report_link'] = '/static-job-reports/%s/scan-build/' % j.id
        else:
            info['job_report_link'] = info['job_link']
        if j.machine:
            info['job_machine_link'] = '/machine/%s' % j.machine.name
        if not j.is_finished():
            unfinished += 1
            if j.machine is None:
                info['status'] = 'pending'
            else:
                info['status'] = 'running'
        else:
            info['status'] = 'finished'

        source_jobs_info.append(info)

    binaries_jobs = session.query(Job)\
        .options(joinedload('machine'))\
        .join(Binary, Job.package_id == Binary.package_id)\
        .filter(Binary.source_id == package.source_id)\
        .order_by(Job.type, Job.subtype, Binary.name)\
        .all()

    binaries_jobs_info = []
    for j in binaries_jobs:
        info = {}
        info['job'] = j
        info['job_link'] = '/report/%s/%s/%s/%s#full_log' % (package_name, this_version, j.type, j.id)
        if j.machine:
            info['job_machine_link'] = '/machine/%s' % j.machine.name
        if not j.is_finished():
            unfinished += 1
            if j.machine:
                info['status'] = 'running'
            else:
                info['status'] = 'pending'
        else:
            info['status'] = 'finished'
        binaries_jobs_info.append(info)

    return render_template('source.html', **{
        "desc": desc,
        "multiple_runs": multiple_runs,
        "runs_info": runs_info,
        "latest_run": latest_run,
        "multiple_versions": multiple_versions,
        "latest_version": latest_version,
        "versions_info": versions_info,
        "package": package,
        "package_job_status": (total, unfinished),
        "source_jobs_info": source_jobs_info,
        "binaries_jobs_info": binaries_jobs_info
    })


@frontend.route("/machine/<machine_name>")
def machine(machine_name):
    session = Session()
    # FIXME : unsafe code, catch exceptions
    machine = session.query(Machine).filter(Machine.name == machine_name).one()
    return render_template('machine.html', **{
        "machine": machine
    })


@frontend.route("/worker/<worker_login>")
def worker(worker_login):
    session = Session()
    # FIXME : unsafe code, catch exceptions                                                                            
    user = session.query(User).filter(User.login == worker_login).one()

    ur = UserRepository(user)
    dput_upload_profile = ur.generate_dputprofile()

    return render_template('worker.html', **{
        "worker": user,
        "dput_upload_profile": dput_upload_profile
    })

@frontend.route("/repository/<worker_login>")
def repository(worker_login):
    session = Session()
    # FIXME : unsafe code, catch exceptions
    user = session.query(User).filter(User.login == worker_login).one()

    ur = UserRepository(user)
    apt_binary_list = ur.generate_aptbinarylist()
    apt_source_list = ur.generate_aptsourcelist()

    return render_template('repository.html', **{
        "worker": user,
        "apt_binary_list": apt_binary_list,
        "apt_source_list": apt_source_list
    })


@frontend.route("/report/<job_id>/")
@frontend.route("/report/<package_name>/<version>/<job_type>/<job_id>/")
def report(job_id, package_name="", version="", job_type=""):
# TODO : design architecture Pending, firewose ?
#    report = Report.load(report_id)
    config = Config()
    session = Session()
    job_query = session.query(Job).filter(Job.id == job_id)
    try:
        job = job_query.one()
    except:
        raise Exception("This resource does not exist")

    job_info = {}
    job_info['job'] = job
    time_diff = job.finished_at - job.assigned_at
    hours, remainder = divmod(time_diff.total_seconds(), 3600)
    minutes, seconds = divmod(remainder, 60)
    job_info['job_runtime'] = '%dh %02dm %02ds' % (hours, minutes, seconds)
    job_info['job_runtime_type'] = type(job.finished_at - job.assigned_at)
    job_info['machine_link'] = "/machine/%s" % job.machine.name
    if job.package.type == "source":
        job_info['package_link'] = '/source/%s/%s/%s/%s' % (job.package.user.login, job.package.name, job.package.version, job.package.run)
    else:
        pool = os.path.join(config.get('paths', 'pool_url'), str(job.package.source.package_id), job.package.arch, job.package.deb)
        job_info['deb_link'] = pool
        job_info['source_link'] = '/source/%s/%s/%s/%s' % (job.package.source.user.login, job.package.source.name, job.package.source.version, job.package.source.run)

    log_path = os.path.join(config.get('paths', 'jobs_path'),
                            job_id, 'log.txt')

    firehose_link = "/static-job-reports/%s/firehose.xml" % job_id
    log_link = "/static-job-reports/%s/log.txt" % job_id

    ### SCANDALOUS HACK
    if job.type == 'clanganalyzer':
        scanbuild_link = "/static-job-reports/%s/scan-build/" % job_id
    else:
        scanbuild_link = ""

    log = []
    if os.path.exists(log_path):
        log = (x.decode('utf-8') for x in open(log_path, 'r'))

    return render_template('report.html', **{
        "job_info": job_info,
        "log_link": log_link,
        "firehose_link": firehose_link,
        "scanbuild_link": scanbuild_link,
        "log": log,
    })


@frontend.route("/report/firehose/<job_id>/")
def report_firehose(job_id):
    config = Config()
    firehose_path = os.path.join(config.get('paths', 'jobs_path'),
                                 job_id, 'firehose.xml')

    if os.path.exists(firehose_path):
        return send_file(firehose_path, mimetype='application/xml',
                         as_attachment=True, attachment_filename='firehose.xml')


@frontend.route("/report/log/<job_id>/")
def report_log(job_id):
    config = Config()
    log_path = os.path.join(config.get('paths', 'jobs_path'),
                            job_id, 'log')

    if os.path.exists(log_path):
        return send_file(log_path, mimetype='text/plain', as_attachment=True,
                         attachment_filename='log.txt')


@frontend.route('/_search_package')
def search_package():
    search = request.args.get('search[term]')
    session = Session()
    packages_query = session.query(Source.name)\
        .filter(Source.name.startswith(search)).group_by(Source.name).limit(10)
    result = [r[0] for r in packages_query]
    return jsonify(result)

@frontend.route('/_search_maintainer')
def search_maintainer():
    search = request.args.get('search[term]')
    session = Session()
    print "foo" + search
    maintainers_query = session.query(Source.maintainer)\
        .filter(Source.maintainer.contains(search))\
        .group_by(Source.maintainer).limit(10)
    result = [r[0] for r in maintainers_query]
    return jsonify(result)


@frontend.route('/about')
def about():
    return render_template('about.html')
