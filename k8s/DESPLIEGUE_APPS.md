# Despliegue de apps en AKS (GitHub Container Registry)

Guía rápida para aplicar manifiestos y desplegar imágenes publicadas en GHCR.

## Comandos básicos de Kubernetes
- `kubectl apply -f <archivo>`: aplica/actualiza recursos.
- `kubectl get pods -n <ns>` y `kubectl get svc -n <ns>`: inventario de pods/servicios.
- `kubectl logs <pod> -n <ns>` y `kubectl describe pod <pod> -n <ns>`: depurar.
- `kubectl port-forward svc/<svc> 8080:80 -n <ns>`: exponer un servicio localmente.

## Despliegue del frontend
1) Asegúrate de tener la imagen en GHCR (workflow `frontend-docker.yml` genera `ghcr.io/<OWNER>/dsrp-frontend:latest`).
2) Edita `k8s/frontend.yaml` y reemplaza `ghcr.io/<OWNER>/dsrp-frontend:latest` con tu ruta real (usuario/org de GHCR). Si la imagen es privada, crea un pull secret y actívalo en `imagePullSecrets`.
3) Aplica el manifiesto:
```bash
kubectl apply -f k8s/frontend.yaml
```
4) Verifica estado e IP pública (Service tipo LoadBalancer):
```bash
kubectl get pods
kubectl get svc frontend
```
5) Abre la IP/hostname del servicio `frontend` en el navegador.

> Nota: ajusta `replicas`, recursos y namespace en `k8s/frontend.yaml` según tu entorno.
