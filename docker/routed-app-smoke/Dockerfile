ARG ROUTER_BASE_IMAGE=ai-team/router:contract-1
FROM ${ROUTER_BASE_IMAGE}

LABEL org.opencontainers.image.title="AI-Team routed-app smoke fixture"
LABEL org.opencontainers.image.description="Ephemeral TCP service used only to verify the Host routed-app manager."

ARG APP_MARKER=ROUTED_APP_OK
RUN printf '%s' "${APP_MARKER}" > /opt/routed-app-marker

EXPOSE 18080/tcp

HEALTHCHECK --interval=1s --timeout=2s --start-period=2s --retries=10 \
  CMD ["/bin/sh", "-c", "printf probe | /usr/bin/socat -T 1 - TCP:127.0.0.1:18080,connect-timeout=1 | grep -q ROUTED_APP_"]

ENTRYPOINT ["/usr/bin/socat"]
CMD ["TCP-LISTEN:18080,reuseaddr,fork", "SYSTEM:cat /opt/routed-app-marker"]
