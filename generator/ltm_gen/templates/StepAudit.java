package __PKG__;

import java.io.IOException;
import java.net.URL;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.CopyOnWriteArrayList;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;

/**
 * Generated. Reads what the data-audit addon recorded for a process instance
 * (GraphQL at /data-audit/q) after each step of a test scenario, checks it
 * against what the step sent, and collects a step-by-step report written to
 * logs/&lt;processId&gt;-audit.json. A step with nothing recorded fails.
 */
public final class StepAudit {

    private static final Map<String, List<Map<String, Object>>> REPORTS = new ConcurrentHashMap<>();
    private static final Comparator<JsonNode> SAME_VALUE = (a, b) -> {
        if (a.isNumber() && b.isNumber()) {
            return a.decimalValue().compareTo(b.decimalValue());
        }
        if (a.isTextual() && b.isArray()) {
            List<Long> want = temporalParts(a.asText());
            if (want != null && b.size() <= want.size()) {
                for (int i = 0; i < want.size(); i++) {
                    if (want.get(i) != b.path(i).asLong(0)) {
                        return 1;
                    }
                }
                return 0;
            }
        }
        return a.equals(b) ? 0 : 1;
    };

    private static final java.util.regex.Pattern TEMPORAL = java.util.regex.Pattern.compile(
            "(\\d{4})-(\\d{2})-(\\d{2})(?:T(\\d{2}):(\\d{2})(?::(\\d{2})(?:\\.(\\d{1,9}))?)?)?");

    /** The audit records java.time values as arrays: LocalDate 2027-01-31 is [2027,1,31]. */
    private static List<Long> temporalParts(String text) {
        java.util.regex.Matcher m = TEMPORAL.matcher(text);
        if (!m.matches()) {
            return null;
        }
        List<Long> parts = new ArrayList<>();
        for (int g = 1; g <= 6; g++) {
            parts.add(m.group(g) == null ? 0L : Long.parseLong(m.group(g)));
        }
        String nanos = m.group(7) == null ? "0" : (m.group(7) + "000000000").substring(0, 9);
        parts.add(Long.parseLong(nanos));
        return parts;
    }

    private static final Set<String> TERMINAL = Set.of("COMPLETED", "ABORTED", "ERROR");

    private final URL url;
    private final ObjectMapper mapper;
    private final String processId;
    private final List<Map<String, Object>> steps = new ArrayList<>();
    private final Map<String, Object> scenario = new LinkedHashMap<>();
    private final HttpClient http = HttpClient.newHttpClient();
    private Snapshot last = Snapshot.EMPTY;

    public StepAudit(URL url, ObjectMapper mapper, String processId, String scenarioName) {
        this.url = url;
        this.mapper = mapper;
        this.processId = processId;
        scenario.put("scenario", scenarioName);
        scenario.put("source", "data-audit GraphQL " + url.getPath());
        scenario.put("steps", steps);
        REPORTS.computeIfAbsent(processId, k -> new CopyOnWriteArrayList<>()).add(scenario);
    }

    record Snapshot(List<JsonNode> nodes, ObjectNode variables, List<JsonNode> tasks, String status) {
        static final Snapshot EMPTY = new Snapshot(List.of(), new ObjectMapper().createObjectNode(), List.of(), null);
    }

    /** Checks the step that just ran: something was recorded, the node was left, and
     *  every variable the step sent was recorded with the value sent. */
    public void step(String step, String instanceId, String node, Map<String, ?> sent) {
        scenario.put("processInstanceId", instanceId);
        Snapshot now = snapshot(instanceId);
        List<String> problems = new ArrayList<>();
        Set<String> seen = new HashSet<>();
        last.nodes().forEach(n -> seen.add(n.path("eventId").asText()));
        List<JsonNode> added = now.nodes().stream().filter(n -> !seen.contains(n.path("eventId").asText())).toList();
        if (added.isEmpty()) {
            problems.add("nothing was recorded for this step");
        }
        // BAMOE 9.6 does not always record EXIT for the start node; a task must be left (EXIT).
        boolean start = "start".equals(step);
        if (added.stream().noneMatch(n -> node.equals(n.path("nodeName").asText())
                && ("EXIT".equals(n.path("eventType").asText())
                    || start && "ENTER".equals(n.path("eventType").asText())))) {
            problems.add("node history has no " + (start ? "record" : "exit") + " of '" + node + "' for this step");
        }
        ObjectNode sentTree = mapper.createObjectNode();
        sent.forEach((k, v) -> sentTree.set(k, mapper.valueToTree(v)));
        sentTree.fields().forEachRemaining(e -> {
            JsonNode recorded = now.variables().get(e.getKey());
            if (recorded == null) {
                if (!e.getValue().isNull()) {
                    problems.add("variable '" + e.getKey() + "' was sent but nothing was recorded");
                }
            } else if (!e.getValue().equals(SAME_VALUE, recorded)) {
                problems.add("variable '" + e.getKey() + "' was sent as " + e.getValue() + " but recorded as " + recorded);
            }
        });
        Map<String, Object> entry = new LinkedHashMap<>();
        entry.put("step", step);
        entry.put("node", node);
        entry.put("sent", sentTree);
        entry.put("variablesBefore", last.variables());
        entry.put("variablesAfter", now.variables());
        entry.put("nodeEvents", added.stream().map(StepAudit::event).toList());
        entry.put("taskStates", now.tasks());
        entry.put("problems", problems);
        steps.add(entry);
        last = now;
        if (!problems.isEmpty()) {
            throw new AssertionError(processId + " step '" + step + "': " + String.join("; ", problems));
        }
    }

    /** End of a scenario: recorded status, an end event when completed, and which
     *  service tasks ran (by name) according to the node history. */
    public void finish(String instanceId, String status, List<String> ran, List<String> notRan) {
        Snapshot now = snapshot(instanceId);
        List<String> problems = new ArrayList<>();
        if (!status.equals(now.status())) {
            problems.add("recorded status is " + now.status() + ", expected " + status);
        }
        Set<String> entered = new HashSet<>();
        now.nodes().stream().filter(n -> "ENTER".equals(n.path("eventType").asText()))
                .forEach(n -> entered.add(n.path("nodeName").asText()));
        if ("COMPLETED".equals(status) && now.nodes().stream().noneMatch(n -> "EndNode".equals(n.path("nodeType").asText()))) {
            problems.add("no end event in the node history");
        }
        ran.stream().filter(n -> !entered.contains(n)).forEach(n -> problems.add("'" + n + "' did not run"));
        notRan.stream().filter(entered::contains).forEach(n -> problems.add("'" + n + "' ran but should not have"));
        scenario.put("status", now.status());
        scenario.put("nodeHistory", now.nodes().stream().map(StepAudit::event).toList());
        scenario.put("finalVariables", now.variables());
        scenario.put("problems", problems);
        if (!problems.isEmpty()) {
            throw new AssertionError(processId + " end: " + String.join("; ", problems));
        }
    }

    private static String event(JsonNode n) {
        return n.path("eventType").asText() + " " + n.path("nodeType").asText() + " '" + n.path("nodeName").asText() + "'";
    }

    // Without pagination the audit queries return only the newest 10 rows.
    private static final String ALL_ROWS = "pagination: { limit: 100000, offset: 0 }";

    private Snapshot snapshot(String id) {
        String q = "{ nodes: GetAllProcessInstancesNodeByProcessInstanceId(processInstanceId: \"" + id + "\", " + ALL_ROWS + ") { eventId eventType nodeType nodeName nodeInstanceId } "
                + "variables: GetAllProcessInstancesVariableByProcessInstanceId(processInstanceId: \"" + id + "\", " + ALL_ROWS + ") { variableName variableValue } "
                + "states: GetProcessInstancesStateHistory(processInstanceId: \"" + id + "\", " + ALL_ROWS + ") { eventType state } "
                + "tasks: GetAllUserTaskInstanceState(" + ALL_ROWS + ") { processInstanceId userTaskInstanceId name state eventType } }";
        JsonNode data = query(q);
        List<JsonNode> nodes = new ArrayList<>();
        data.path("nodes").forEach(nodes::add);
        java.util.Collections.reverse(nodes); // the query returns newest first
        ObjectNode variables = mapper.createObjectNode();
        data.path("variables").forEach(v -> variables.set(v.path("variableName").asText(), v.path("variableValue")));
        List<JsonNode> tasks = new ArrayList<>();
        data.path("tasks").forEach(t -> {
            if (id.equals(t.path("processInstanceId").asText())) {
                tasks.add(t);
            }
        });
        // A state event that ends the instance is the last one, even if it has the
        // same timestamp as the ACTIVE event (start and end in one unit of work).
        String status = null;
        for (JsonNode st : data.path("states")) {
            String type = st.path("eventType").asText();
            if (TERMINAL.contains(type)) {
                status = type;
                break;
            }
            if (status == null) {
                status = type;
            }
        }
        return new Snapshot(nodes, variables, tasks, status);
    }

    private JsonNode query(String q) {
        try {
            String body = mapper.writeValueAsString(Map.of("query", q));
            HttpResponse<String> r = http.send(HttpRequest.newBuilder(url.toURI())
                    .header("Content-Type", "application/json")
                    .POST(HttpRequest.BodyPublishers.ofString(body)).build(), HttpResponse.BodyHandlers.ofString());
            JsonNode json = mapper.readTree(r.body());
            if (r.statusCode() != 200 || json.has("errors")) {
                throw new AssertionError("data-audit query failed (" + r.statusCode() + "): " + r.body());
            }
            return json.path("data");
        } catch (IOException | InterruptedException | java.net.URISyntaxException e) {
            throw new AssertionError("data-audit query failed: " + e, e);
        }
    }

    /** Writes logs/&lt;processId&gt;-audit.json with every scenario run so far. */
    public static void write(String processId) throws IOException {
        Path out = Path.of("logs", processId + "-audit.json");
        Files.createDirectories(out.getParent());
        Map<String, Object> report = new LinkedHashMap<>();
        report.put("processId", processId);
        report.put("scenarios", REPORTS.getOrDefault(processId, List.of()));
        new ObjectMapper().writerWithDefaultPrettyPrinter().writeValue(out.toFile(), report);
    }
}
