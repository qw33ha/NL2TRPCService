service:
  name: {{ server }}
  module: {{ module_path }}

global:
  namespace: ${TRPC_NAMESPACE:-default}
  env_name: ${TRPC_ENV:-dev}
  container_name: ${POD_NAME}
  local_ip: ${POD_IP}
  admin_port: 10001
  enable_set: N


server:
  app: {{ app }}
  server: {{ server }}
  bin_path: /usr/local/trpc/bin/
  conf_path: /usr/local/trpc/conf/
  data_path: /usr/local/trpc/data/
  close_wait_time: 1000
  max_close_wait_time: 2000
  service:
{% if rpc_enabled %}
    - name: {{ trpc_service_name }}
      ip: 0.0.0.0
      port: {{ trpc_port | default(9000) }}
      network: tcp
      protocol: trpc
      timeout: 1000
      idle_timeout: 10000
{% endif %}
{% if http_enabled %}
    - name: {{ http_service_name }}
      ip: 0.0.0.0
      port: {{ http_port | default(8080) }}
      network: tcp
      protocol: http_no_protocol
      timeout: 1000
      idle_timeout: 10000
{% endif %}
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
{% if db_enabled and db_type == "postgres" %}
    - name: {{ db_service_name }}
      target: dsn://postgres://${POSTGRES_USER:-{{ db_user }}}:${{ '{' }}{{ db_password_env }}{{ '}' }}@{{ db_host }}:{{ db_port }}/{{ db_name }}?sslmode=${POSTGRES_SSLMODE:-require}
      timeout: 1000
{% endif %}
{% if kafka_consumer_enabled or kafka_producer_enabled %}
    - name: {{ kafka_service_name }}
      target: kafka://{{ kafka_producer_brokers }}
      timeout: 1000
{% endif %}
