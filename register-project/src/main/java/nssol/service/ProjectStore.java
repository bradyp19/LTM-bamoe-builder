package nssol.service;

import java.util.List;
import java.util.concurrent.CopyOnWriteArrayList;

import jakarta.enterprise.context.ApplicationScoped;
import nssol.model.ProjectRegistration;

/**
 * TEST DOUBLE — documented boundary, not a real persistence implementation.
 *
 * The LTM documents specify that the "Write / Save NSSOL Projects Record" node
 * creates a new NSSOL_PROJECTS row or updates the existing row (D03 Figure 1),
 * but do NOT specify the write API, insert-vs-update algorithm, or failure
 * semantics (supplementation request SR-4). This in-memory store records what
 * the service task received so tests can demonstrate the documented flow;
 * real persistence is a downstream design decision.
 */
@ApplicationScoped
public class ProjectStore {

    public record SaveCall(ProjectRegistration registration) {}

    private static final List<SaveCall> SAVES = new CopyOnWriteArrayList<>();

    public ProjectRegistration save(ProjectRegistration projectRegistration) {
        SAVES.add(new SaveCall(projectRegistration));
        return projectRegistration;
    }

    public static List<SaveCall> saves() {
        return List.copyOf(SAVES);
    }

    public static void clear() {
        SAVES.clear();
    }
}
