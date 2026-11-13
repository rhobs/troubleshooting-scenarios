"""Set up and check the cluster permissions used by Agentic evals."""

import argparse
import json
import subprocess
import sys


NAMESPACE = "openshift-lightspeed"
LABEL = "troubleshooting-scenarios/rbac"
LABEL_VALUE = "agentic"
DEPLOYMENTS = (
    "lightspeed-agentic-operator-controller-manager",
    "lightspeed-agentic-operator",
)


def oc(*args, resource=None):
    result = subprocess.run(
        ["oc", *args], input=json.dumps(resource) if resource is not None else None,
        text=True, capture_output=True, check=True,
    )
    return result.stdout.strip()


def can_i(account, verb, resource, *scope):
    try:
        return oc("auth", "can-i", verb, resource, *(scope or ("--all-namespaces",)),
                  f"--as=system:serviceaccount:{NAMESPACE}:{account}") == "yes"
    except subprocess.CalledProcessError as error:
        if error.stdout.strip() == "no":
            return False
        raise


def controller_account(deployment=None):
    for name in (deployment,) if deployment else DEPLOYMENTS:
        value = oc("get", "deployment", name, "-n", NAMESPACE,
                   "--ignore-not-found", "-o", "json")
        if value:
            spec = json.loads(value)["spec"]["template"]["spec"]
            return spec.get("serviceAccountName") or "default"
    raise ValueError("Agentic controller deployment not found")


def subject(name):
    return {"kind": "ServiceAccount", "name": name, "namespace": NAMESPACE}


def has_subject(binding, account):
    return any(all(item.get(key) == value for key, value in subject(account).items())
               for item in binding.get("subjects", []))


def has_role(binding, role):
    return binding.get("roleRef") == {
        "apiGroup": "rbac.authorization.k8s.io", "kind": "ClusterRole", "name": role,
    }


def setup(bindings, requirements):
    for account, role in requirements:
        name = f"troubleshooting-scenarios-agentic-{role}"
        existing = next((item for item in bindings if item["metadata"]["name"] == name), None)
        if existing and (
            existing["metadata"].get("labels", {}).get(LABEL) != LABEL_VALUE
            or not has_role(existing, role)
        ):
            raise ValueError(f"ClusterRoleBinding {name} exists with a different owner or role")
        # Only the active controller belongs in our managed admin binding.
        # Reader bindings keep the sandbox accounts added by the controller.
        if role == "cluster-admin":
            subjects = [subject(account)]
        else:
            subjects = list(existing.get("subjects", [])) if existing else []
            if not existing or not has_subject(existing, account):
                subjects.append(subject(account))
        resource = {
            "apiVersion": "rbac.authorization.k8s.io/v1", "kind": "ClusterRoleBinding",
            "metadata": {"name": name, "labels": {LABEL: LABEL_VALUE}},
            "roleRef": {"apiGroup": "rbac.authorization.k8s.io",
                        "kind": "ClusterRole", "name": role},
            "subjects": subjects,
        }
        if existing:
            resource["metadata"]["resourceVersion"] = existing["metadata"]["resourceVersion"]
        oc("apply", "-f", "-", resource=resource)


def check(bindings, requirements):
    for account, role in requirements:
        if not any(has_role(item, role) and has_subject(item, account) for item in bindings):
            raise ValueError(f"no {role} ClusterRoleBinding has subject {NAMESPACE}/{account}")
    controller = requirements[-1][0]
    for account, verb, resource in (
        ("lightspeed-agent", "list", "pods"),
        (controller, "create", "clusterroles.rbac.authorization.k8s.io"),
        (controller, "escalate", "clusterroles.rbac.authorization.k8s.io"),
        (controller, "bind", "clusterroles.rbac.authorization.k8s.io"),
        (controller, "update", "clusterrolebindings.rbac.authorization.k8s.io"),
    ):
        if not can_i(account, verb, resource):
            raise ValueError(f"{NAMESPACE}/{account} cannot {verb} {resource}")
    if not can_i("lightspeed-agent", "get", "pods", "--subresource=log", "--all-namespaces"):
        raise ValueError(f"{NAMESPACE}/lightspeed-agent cannot read pod logs")
    if not can_i("lightspeed-agent", "get", "prometheuses.monitoring.coreos.com/k8s",
                 "--subresource=api", "-n", "openshift-monitoring"):
        raise ValueError(f"{NAMESPACE}/lightspeed-agent cannot read the monitoring API")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--setup", action="store_true")
    parser.add_argument("--deployment", choices=DEPLOYMENTS)
    args = parser.parse_args()
    try:
        controller = controller_account(args.deployment)
        requirements = [
            ("lightspeed-agent", "cluster-reader"),
            ("lightspeed-agent", "cluster-monitoring-view"),
            (controller, "cluster-admin"),
        ]
        bindings = json.loads(oc("get", "clusterrolebindings", "-o", "json"))["items"]
        if args.setup:
            setup(bindings, requirements)
            bindings = json.loads(oc("get", "clusterrolebindings", "-o", "json"))["items"]
        check(bindings, requirements)
    except (ValueError, KeyError, subprocess.CalledProcessError) as error:
        detail = (error.stderr.strip() or str(error)) if isinstance(error, subprocess.CalledProcessError) else str(error)
        print(f"ERROR: Agentic RBAC check failed: {detail}\n"
              "Run make setup-ols-agentic with cluster-admin access.", file=sys.stderr)
        return 1
    print("Agentic reader, monitoring, and controller permissions are ready.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
