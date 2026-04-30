CarbonScaler + MPIJob Setup Guide

This guide walks through setting up and running the CarbonScaler controller with Kubeflow MPIJobs on a Kubernetes cluster.

1. (Optional) Activate Python Virtual Environment

If your project uses a virtual environment:

source .venv/bin/activate
2. Ensure Kubernetes Cluster is Running

Make sure your cluster (e.g., Minikube, Docker Desktop, or remote cluster) is up:

kubectl get nodes
3. Deploy CarbonScaler Controller

Apply your controller manifests (adjust path if needed):

kubectl apply -f src/config/

Verify controller is running:

kubectl get pods -n system

You should see:

controller-manager
carbon-service
power-server
status-server
4. Install Custom Resource Definitions (CRDs)

Apply the CarbonScaler CRDs:

kubectl apply -f src/config/crd/bases/

Verify:

kubectl get crds | grep carbonscaler.io

Expected output:

carbonscalermpijobs.carbonscaler.io
5. Install Kubeflow Training Operator

Ensure the Kubeflow MPI operator is installed:

kubectl get pods -n kubeflow

You should see:

training-operator
6. Fix RBAC Permissions (CRITICAL)

By default, the training operator may not have permissions to manage cluster resources.

Check current binding:

kubectl describe clusterrolebinding training-operator

If it incorrectly points to:

ServiceAccount: controller-manager (namespace: system)

Fix it:

kubectl patch clusterrolebinding training-operator \
  --type='json' \
  -p='[
    {"op":"replace","path":"/subjects/0/name","value":"training-operator"},
    {"op":"replace","path":"/subjects/0/namespace","value":"kubeflow"}
  ]'

Restart the operator:

kubectl rollout restart deployment training-operator -n kubeflow
7. Create Job Profile ConfigMap

Apply the job profile:

kubectl apply -f jobs/nbody100k-profile.yaml

Verify:

kubectl get configmap nbody100k -n system
8. Launch CarbonScaler MPI Job

Apply the job:

kubectl apply -f jobs/mpi_job.yaml

Verify CarbonScaler resource:

kubectl get carbonscalermpijobs -n system
9. Verify MPIJob Creation

Check underlying MPIJob:

kubectl get mpijobs -n system

Inspect details:

kubectl describe mpijob nbody -n system
10. Verify Pods Are Running
kubectl get pods -n system

Expected:

nbody-launcher
nbody-worker-0
11. Debugging Tips
Check Controller Logs
kubectl logs -n system deployment/controller-manager
Check Training Operator Logs
kubectl logs -n kubeflow deployment/training-operator
Check MPIJob Status
kubectl get mpijob nbody -n system -o yaml
Common Issues
❌ MPIJob stuck / not launching
Likely RBAC issue → fix ClusterRoleBinding (Step 6)
❌ CRD not found
Ensure CRDs applied from src/config/crd/bases/
❌ No pods created
Check training operator logs for permission errors
12. What “Success” Looks Like

You should see:

Controller logs computing schedules

MPIJob status:

type: Running

Pods:

nbody-launcher
nbody-worker-0
Notes
CarbonScaler dynamically controls MPIJob replicas based on carbon intensity.
The MPIJob is owned by the CarbonScalerMPIJob custom resource.
Status syncing from MPIJob → CarbonScaler CR may require additional controller logic.