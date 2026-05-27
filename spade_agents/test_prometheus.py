# from prometheus_api_client import PrometheusConnect
# NAMESPACE = "nrprediger"
# def prometheus_query(upf_name, resource):
#     prom = PrometheusConnect(url ="http://localhost:35235/", disable_ssl=True)
#     # Query (Ex: rate(container_cpu_usage_seconds_total{namespace="nrprediger", pod=~"upf-.*", container="upf"}[1m]))
#     query = prom.custom_query(f"rate(container_{resource}_usage_seconds_total{{namespace=\"{NAMESPACE}\", pod=~\"{upf_name}-.*\", container=\"{upf_name}\"}}[30s])")
#     # Print the result
#     if query:
#         resource_usage = query[0]['value'][1]
#         return float(resource_usage)
#     else:
#         return None
# def main():
#     upf_name = "upf1"
#     resource = "cpu"
#     result = prometheus_query(upf_name, resource)
#     print(f"Prometheus query result for {resource} usage of {upf_name}: {result}")
# if __name__ == "__main__":
#     main()
from spade_llm import LLMProvider
import inspect

print(inspect.signature(LLMProvider.get_llm_response))