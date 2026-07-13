service:
  name: {{ server }}
  module: {{ module_path }}

global:
  namespace: ${TRPC_NAMESPACE:-default}
  env_name: ${TRPC_ENV:-dev}

server:
  app: {{ app }}
  server: {{ server }}
  service:
    - name: {{ trpc_service_name }}
      ip: 0.0.0.0
      port: {{ trpc_port | default(9000) }}
      network: tcp
      protocol: trpc
      timeout: 1000
      idle_timeout: 10000
{% if kafka_consumer_enabled %}
    - name: {{ kafka_service_name }}
      address: {{ kafka_producer_brokers }}
      protocol: kafka
      timeout: 1000
{% endif %}

client:
  service:
{% if db_enabled and db_type == "mysql" %}
    - name: {{ db_service_name }}
      target: dsn://${MYSQL_USER:-{{ db_user }}}:${{ '{' }}{{ db_password_env }}{{ '}' }}@tcp({{ db_host }}:{{ db_port }})/{{ db_name }}?parseTime=true&interpolateParams=true
      timeout: 1000
{% endif %}
{% if db_enabled and db_type == "redis" %}
    - name: {{ db_service_name }}
      target: redis://:${{ '{' }}{{ db_password_env }}{{ '}' }}@{{ db_host }}:{{ db_port }}/0
      timeout: 1000
{% endif %}
{% if kafka_consumer_enabled or kafka_producer_enabled %}
    - name: {{ kafka_service_name }}
      target: kafka://{{ kafka_producer_brokers }}
      timeout: 1000
{% endif %}

http:
  port: {{ http_port | default(8080) }}
  health_path: {{ health_path }}
