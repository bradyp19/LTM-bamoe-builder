package nssol;

import static org.assertj.core.api.Assertions.assertThat;

import java.util.Map;

import jakarta.inject.Inject;
import jakarta.inject.Named;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.kie.kogito.Model;
import org.kie.kogito.auth.SecurityPolicy;
import org.kie.kogito.process.Process;
import org.kie.kogito.process.ProcessInstance;
import org.kie.kogito.services.identity.StaticIdentityProvider;

import io.quarkus.test.junit.QuarkusTest;
import nssol.model.ProjectRegistration;
import nssol.service.ProjectStore;

// Generated process test. Scenarios from spec evidence: D03 Figure 1 (image-inspected 2026-11-09), D03 ¶24–28, D04 ¶24–79
@QuarkusTest
class RegisterProjectProcessTest {

    private static final SecurityPolicy USER =
            SecurityPolicy.of(new StaticIdentityProvider("tester"));

    @Inject
    @Named("registerProject")
    Process<? extends Model> process;

    @BeforeEach
    void clearStore() {
        ProjectStore.clear();
    }

    @Test
    void createProject_submitsAndSaves() {
        var model = process.createModel();
        ProjectRegistration p = new ProjectRegistration();
        p.setProjectName("Test Tower Construction");
        p.setStatus("In-Progress");
        p.setIsActive(true);
        model.update(Map.of("isUpdate", false, "cancel", false, "projectRegistration", p));
        var instance = process.createInstance(model);
        instance.start();
        assertThat(instance.status()).isEqualTo(ProcessInstance.STATE_ACTIVE);
        var items = instance.workItems(USER);
        assertThat(items).hasSize(1);
        assertThat(items.get(0).getName()).isEqualTo("Fill Project Registration Form");
        instance.completeWorkItem(items.get(0).getId(), Map.of("cancel", false, "projectRegistration", p), USER);
        assertThat(instance.status()).isEqualTo(ProcessInstance.STATE_COMPLETED);
        assertThat(ProjectStore.saves()).hasSize(1);
        assertThat(ProjectStore.saves().get(0).registration().getProjectName()).isEqualTo("Test Tower Construction");
        assertThat(ProjectStore.saves().get(0).registration().getProjectId()).isEqualTo(null);
    }
    @Test
    void updateProject_submitsAndSaves() {
        var model = process.createModel();
        ProjectRegistration p = new ProjectRegistration();
        p.setProjectId(42);
        p.setProjectName("Test Tower Construction");
        p.setIsActive(true);
        model.update(Map.of("isUpdate", true, "cancel", false, "projectRegistration", p));
        var instance = process.createInstance(model);
        instance.start();
        assertThat(instance.status()).isEqualTo(ProcessInstance.STATE_ACTIVE);
        var items = instance.workItems(USER);
        assertThat(items).hasSize(1);
        assertThat(items.get(0).getName()).isEqualTo("Fill Project Registration Form");
        instance.completeWorkItem(items.get(0).getId(), Map.of("cancel", false, "projectRegistration", p), USER);
        assertThat(instance.status()).isEqualTo(ProcessInstance.STATE_COMPLETED);
        assertThat(ProjectStore.saves()).hasSize(1);
        assertThat(ProjectStore.saves().get(0).registration().getProjectId()).isEqualTo(42);
    }
    @Test
    void cancel_writesNothing() {
        var model = process.createModel();
        ProjectRegistration p = new ProjectRegistration();
        p.setProjectName("Test Tower Construction");
        p.setIsActive(true);
        model.update(Map.of("isUpdate", false, "cancel", false, "projectRegistration", p));
        var instance = process.createInstance(model);
        instance.start();
        assertThat(instance.status()).isEqualTo(ProcessInstance.STATE_ACTIVE);
        var items = instance.workItems(USER);
        assertThat(items).hasSize(1);
        assertThat(items.get(0).getName()).isEqualTo("Fill Project Registration Form");
        instance.completeWorkItem(items.get(0).getId(), Map.of("cancel", true, "projectRegistration", p), USER);
        assertThat(instance.status()).isEqualTo(ProcessInstance.STATE_COMPLETED);
        assertThat(ProjectStore.saves()).hasSize(0);
    }
}
